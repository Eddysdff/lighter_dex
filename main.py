#!/usr/bin/env python3
"""
Lighter Volume Bot - 主程序入口
用于在Lighter DEX上刷交易量获取积分
"""
import asyncio
import signal
import sys
import os
from typing import Optional
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
import argparse

from config import config, validate_config, print_config, TradingStrategy
from lighter_client import LighterClient
from strategies import create_strategy, BaseStrategy
from monitor import VolumeMonitor, monitoring_loop

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level=config.log_level
)
logger.add(
    "logs/volume_bot_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG"
)

class VolumeBot:
    """主机器人类"""
    
    def __init__(self):
        self.client: Optional[LighterClient] = None
        self.strategy: Optional[BaseStrategy] = None
        self.monitor: Optional[VolumeMonitor] = None
        self.running = False
        self.tasks = []
        
    async def initialize(self):
        """初始化机器人"""
        logger.info("🚀 初始化 Lighter Volume Bot...")
        
        # 验证配置
        try:
            validate_config()
            print_config()
        except ValueError as e:
            logger.error(f"❌ 配置错误: {e}")
            sys.exit(1)
            
        # 创建客户端
        self.client = LighterClient()
        await self.client.connect()
        
        # 检查API连接
        if not await self.client.check_api_status():
            logger.error("❌ 无法连接到Lighter API")
            sys.exit(1)
            
        logger.info("✅ API连接成功")
        
        # 检查账户余额
        await self._check_balance()
        
        # 创建策略
        self.strategy = create_strategy(config.strategy, self.client, config.symbol)
        logger.info(f"✅ 策略已加载: {config.strategy.value}")
        
        # 创建监控器
        self.monitor = VolumeMonitor()
        self.monitor.daily_target = config.daily_volume_target
        
        logger.info("✅ 初始化完成")
        
    async def _check_balance(self):
        """检查账户余额"""
        try:
            balances = await self.client.get_balance()
            
            logger.info("💰 账户余额:")
            for balance in balances:
                if balance.total > 0:
                    logger.info(f"  {balance.asset}: {balance.total:.4f} (可用: {balance.free:.4f})")
                    
            # 检查USDT余额
            usdt_balance = next((b for b in balances if b.asset == "USDT"), None)
            if not usdt_balance or usdt_balance.free < config.max_position_size:
                logger.warning(f"⚠️ USDT余额不足，建议至少准备 {config.max_position_size} USDT")
                
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            
    async def run(self):
        """运行机器人"""
        self.running = True
        logger.info("🤖 Volume Bot 开始运行")
        
        try:
            # 启动策略
            strategy_task = asyncio.create_task(self._run_strategy())
            self.tasks.append(strategy_task)
            
            # 启动监控
            monitor_task = asyncio.create_task(self._run_monitor())
            self.tasks.append(monitor_task)
            
            # 启动统计更新
            stats_task = asyncio.create_task(self._update_stats())
            self.tasks.append(stats_task)
            
            # 启动安全检查
            safety_task = asyncio.create_task(self._safety_check())
            self.tasks.append(safety_task)
            
            # 等待所有任务
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        except KeyboardInterrupt:
            logger.info("⚠️ 收到停止信号")
        except Exception as e:
            logger.error(f"❌ 运行错误: {e}")
        finally:
            await self.shutdown()
            
    async def _run_strategy(self):
        """运行交易策略"""
        while self.running:
            try:
                if config.emergency_stop:
                    logger.warning("🛑 紧急停止已激活")
                    await asyncio.sleep(10)
                    continue
                    
                await self.strategy.execute()
                
                # 根据策略类型调整执行间隔
                if config.strategy == TradingStrategy.SELF_TRADE:
                    await asyncio.sleep(config.order_interval_seconds)
                elif config.strategy == TradingStrategy.GRID:
                    await asyncio.sleep(config.order_interval_seconds * 5)  # 网格策略执行频率较低
                else:
                    await asyncio.sleep(config.order_interval_seconds * 2)
                    
            except Exception as e:
                logger.error(f"策略执行错误: {e}")
                await asyncio.sleep(5)
                
    async def _run_monitor(self):
        """运行监控"""
        await monitoring_loop(self.monitor, interval=config.stats_interval_seconds)
        
    async def _update_stats(self):
        """更新统计数据"""
        while self.running:
            try:
                # 从策略获取统计
                if self.strategy and self.strategy.stats:
                    self.monitor.current_metrics.total_volume = self.strategy.stats.total_volume
                    self.monitor.current_metrics.total_trades = self.strategy.stats.executed_trades
                    self.monitor.current_metrics.total_fees = self.strategy.stats.total_fees
                    self.monitor.current_metrics.realized_pnl = self.strategy.stats.realized_pnl
                    
                # 从客户端获取统计
                if self.client:
                    client_stats = self.client.get_statistics()
                    if client_stats['total_volume'] > self.monitor.current_metrics.total_volume:
                        self.monitor.current_metrics.total_volume = client_stats['total_volume']
                        
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"更新统计错误: {e}")
                await asyncio.sleep(30)
                
    async def _safety_check(self):
        """安全检查"""
        while self.running:
            try:
                # 检查日亏损
                if self.monitor.current_metrics.realized_pnl < -config.max_daily_loss:
                    logger.error(f"🚨 达到最大日亏损限制: {self.monitor.current_metrics.realized_pnl:.2f} USDT")
                    config.emergency_stop = True
                    
                # 检查持仓
                positions = await self.client.get_positions()
                for position in positions:
                    if abs(position.amount * position.mark_price) > config.max_position_size:
                        logger.warning(f"⚠️ 持仓超限: {position.symbol} {position.amount * position.mark_price:.2f} USDT")
                        
                    # 检查止损
                    if position.pnl < -(config.max_position_size * config.stop_loss_percent / 100):
                        logger.error(f"🚨 触发止损: {position.symbol} 亏损 {position.pnl:.2f} USDT")
                        # 平仓逻辑
                        
                # 检查挂单数量
                open_orders = await self.client.get_open_orders(config.symbol)
                if len(open_orders) > config.max_open_orders:
                    logger.warning(f"⚠️ 挂单数量过多: {len(open_orders)}")
                    # 取消部分订单
                    
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"安全检查错误: {e}")
                await asyncio.sleep(60)
                
    async def shutdown(self):
        """关闭机器人"""
        logger.info("🛑 正在关闭 Volume Bot...")
        self.running = False
        
        # 停止策略
        if self.strategy:
            await self.strategy.stop()
            
        # 取消所有任务
        for task in self.tasks:
            if not task.done():
                task.cancel()
                
        # 等待任务结束
        await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # 关闭客户端连接
        if self.client:
            await self.client.close()
            
        # 打印最终统计
        if self.monitor:
            self.monitor.print_dashboard()
            
        logger.info("✅ Volume Bot 已安全关闭")

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Lighter Volume Bot - 刷交易量获取积分")
    
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["self_trade", "grid", "market_make", "hybrid"],
        default="grid",
        help="交易策略 (默认: grid)"
    )
    
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETH-USDT",
        help="交易对 (默认: ETH-USDT)"
    )
    
    parser.add_argument(
        "--volume-target",
        type=float,
        default=100000,
        help="日交易量目标 (默认: 100000 USDT)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟模式，不实际下单"
    )
    
    parser.add_argument(
        "--max-loss",
        type=float,
        default=50,
        help="最大日亏损 (默认: 50 USDT)"
    )
    
    return parser.parse_args()

async def main():
    """主函数"""
    # 解析参数
    args = parse_arguments()
    
    # 更新配置
    if args.strategy:
        config.strategy = TradingStrategy(args.strategy)
    if args.symbol:
        config.symbol = args.symbol
    if args.volume_target:
        config.daily_volume_target = args.volume_target
    if args.dry_run:
        config.dry_run = True
    if args.max_loss:
        config.max_daily_loss = args.max_loss
        
    # 创建并运行机器人
    bot = VolumeBot()
    
    # 设置信号处理
    def signal_handler(sig, frame):
        logger.info("收到终止信号，正在安全退出...")
        bot.running = False
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.initialize()
        await bot.run()
    except Exception as e:
        logger.error(f"致命错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # 打印启动信息
    print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║            🚀 Lighter Volume Bot v1.0 🚀                 ║
║                                                           ║
║         专业的去中心化交易所刷量工具                     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # 加载环境变量
    load_dotenv()
    
    # 运行主程序
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 再见！")
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
        sys.exit(1)