"""
Lighter DEX 交易脚本主程序
"""
import asyncio
import argparse
import sys
from typing import Optional
from loguru import logger
from config import get_config, reload_config
from lighter_client import LighterClient
from risk_manager import RiskManager
from websocket_client import WebSocketClient
from strategies import GridTradingStrategy, MomentumStrategy, ArbitrageStrategy


class LighterTradingBot:
    """Lighter交易机器人"""
    
    def __init__(self):
        """初始化交易机器人"""
        self.config = None
        self.client = None
        self.risk_manager = None
        self.ws_client = None
        self.strategy = None
        
    async def initialize(self):
        """初始化组件"""
        try:
            # 加载配置
            self.config = get_config()
            logger.info(f"配置加载成功: {self.config.network}")
            
            # 初始化客户端
            self.client = LighterClient(self.config)
            logger.info("Lighter客户端初始化成功")
            
            # 初始化风险管理器
            self.risk_manager = RiskManager(self.client, self.config)
            logger.info("风险管理器初始化成功")
            
            # 初始化WebSocket客户端
            self.ws_client = WebSocketClient(self.config)
            await self.ws_client.connect()
            logger.info("WebSocket客户端连接成功")
            
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            raise
            
    async def cleanup(self):
        """清理资源"""
        try:
            # 停止策略
            if self.strategy and self.strategy.is_running:
                await self.strategy.stop()
                
            # 断开WebSocket
            if self.ws_client:
                await self.ws_client.disconnect()
                
            # 关闭客户端
            if self.client:
                await self.client.close()
                
            logger.info("资源清理完成")
            
        except Exception as e:
            logger.error(f"清理资源失败: {e}")
            
    # ==================== 账户功能 ====================
    
    async def show_account_info(self):
        """显示账户信息"""
        try:
            # 获取账户余额
            balance = await self.client.get_account_balance()
            logger.info("=== 账户余额 ===")
            logger.info(f"总余额: ${balance['total_balance']:.2f}")
            logger.info(f"可用余额: ${balance['available_balance']:.2f}")
            logger.info(f"保证金余额: ${balance['margin_balance']:.2f}")
            logger.info(f"未实现盈亏: ${balance['unrealized_pnl']:.2f}")
            logger.info(f"已实现盈亏: ${balance['realized_pnl']:.2f}")
            
            # 获取持仓
            positions = await self.client.get_account_positions()
            if positions:
                logger.info("=== 当前持仓 ===")
                for pos in positions:
                    logger.info(
                        f"{pos['symbol']}: {pos['side']} {pos['size']} @ "
                        f"${pos['entry_price']:.2f} (PnL: ${pos['unrealized_pnl']:.2f})"
                    )
            else:
                logger.info("当前无持仓")
                
            # 获取未完成订单
            open_orders = await self.client.get_open_orders()
            if open_orders:
                logger.info("=== 未完成订单 ===")
                for order in open_orders:
                    logger.info(
                        f"{order['symbol']}: {order['side']} {order['quantity']} @ "
                        f"${order['price']:.2f} ({order['status']})"
                    )
            else:
                logger.info("无未完成订单")
                
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            
    async def show_risk_metrics(self):
        """显示风险指标"""
        try:
            metrics = await self.risk_manager.get_risk_metrics()
            
            logger.info("=== 风险指标 ===")
            logger.info(f"总暴露: ${metrics['total_exposure']:.2f}")
            logger.info(f"杠杆: {metrics['leverage']:.2f}x")
            logger.info(f"持仓数量: {metrics['position_count']}")
            logger.info(f"当前回撤: {metrics['current_drawdown']:.2f}%")
            logger.info(f"夏普比率: {metrics['sharpe_ratio']:.2f}")
            logger.info(f"风险警报: {metrics['risk_alerts']}")
            
            # 监控回撤
            drawdown_info = await self.risk_manager.monitor_drawdown()
            if drawdown_info['is_exceeded']:
                logger.warning("⚠️ 超过最大回撤限制！")
                
        except Exception as e:
            logger.error(f"获取风险指标失败: {e}")
            
    # ==================== 市场数据 ====================
    
    async def show_market_data(self, symbol: str):
        """显示市场数据"""
        try:
            # 获取订单簿
            orderbook = await self.client.get_orderbook(symbol, depth=5)
            logger.info(f"=== {symbol} 订单簿 ===")
            logger.info(f"最佳买价: ${orderbook['best_bid']:.2f}")
            logger.info(f"最佳卖价: ${orderbook['best_ask']:.2f}")
            logger.info(f"价差: ${orderbook['spread']:.4f}")
            
            # 获取最近成交
            trades = await self.client.get_recent_trades(symbol, limit=5)
            if trades:
                logger.info(f"=== 最近成交 ===")
                for trade in trades:
                    logger.info(
                        f"{trade['timestamp'].strftime('%H:%M:%S')}: "
                        f"{trade['side']} {trade['quantity']} @ ${trade['price']:.2f}"
                    )
                    
            # 获取K线数据
            candles = await self.client.get_candlesticks(symbol, interval='1h', limit=5)
            if not candles.empty:
                logger.info(f"=== 最近K线 ===")
                for idx, row in candles.iterrows():
                    logger.info(
                        f"{idx.strftime('%Y-%m-%d %H:%M')}: "
                        f"O:{row['open']:.2f} H:{row['high']:.2f} "
                        f"L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']:.0f}"
                    )
                    
        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            
    # ==================== 交易功能 ====================
    
    async def place_test_order(self, symbol: str):
        """下测试订单"""
        try:
            # 获取当前价格
            orderbook = await self.client.get_orderbook(symbol, depth=1)
            
            # 计算订单价格（比当前价格低5%的买单）
            price = orderbook['best_bid'] * 0.95
            quantity = 0.01  # 小额测试
            
            # 风险检查
            passed, reason = await self.risk_manager.check_position_limits(
                symbol, 'buy', quantity
            )
            
            if not passed:
                logger.warning(f"风险检查未通过: {reason}")
                return
                
            # 下单
            order = await self.client.place_order(
                symbol=symbol,
                side='buy',
                order_type='limit',
                quantity=quantity,
                price=price
            )
            
            logger.info(f"测试订单已下: {order}")
            
            # 等待5秒后取消
            await asyncio.sleep(5)
            await self.client.cancel_order(order_id=order.get('orderId'))
            logger.info("测试订单已取消")
            
        except Exception as e:
            logger.error(f"下测试订单失败: {e}")
            
    # ==================== 策略运行 ====================
    
    async def run_grid_strategy(self, symbol: str):
        """运行网格策略"""
        try:
            self.strategy = GridTradingStrategy(
                client=self.client,
                risk_manager=self.risk_manager,
                ws_client=self.ws_client,
                grid_levels=10,
                grid_spacing=0.005,  # 0.5%间距
                order_size=0.01
            )
            
            logger.info("启动网格交易策略...")
            await self.strategy.start(symbol)
            
        except Exception as e:
            logger.error(f"网格策略运行失败: {e}")
            
    async def run_momentum_strategy(self, symbol: str):
        """运行动量策略"""
        try:
            self.strategy = MomentumStrategy(
                client=self.client,
                risk_manager=self.risk_manager,
                ws_client=self.ws_client,
                lookback_period=20,
                momentum_threshold=0.02,
                position_size=0.1
            )
            
            logger.info("启动动量交易策略...")
            await self.strategy.start(symbol)
            
        except Exception as e:
            logger.error(f"动量策略运行失败: {e}")
            
    async def run_arbitrage_strategy(self, symbol: str):
        """运行套利策略"""
        try:
            self.strategy = ArbitrageStrategy(
                client=self.client,
                risk_manager=self.risk_manager,
                ws_client=self.ws_client,
                spread_threshold=0.002,
                trade_size=0.1
            )
            
            logger.info("启动套利策略...")
            await self.strategy.start(symbol)
            
        except Exception as e:
            logger.error(f"套利策略运行失败: {e}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Lighter DEX 交易机器人')
    parser.add_argument('command', choices=[
        'account', 'risk', 'market', 'test', 
        'grid', 'momentum', 'arbitrage'
    ], help='执行的命令')
    parser.add_argument('--symbol', default='BTC-USDT', help='交易对')
    parser.add_argument('--network', choices=['mainnet', 'testnet'], 
                       default='testnet', help='网络类型')
    
    args = parser.parse_args()
    
    # 创建交易机器人
    bot = LighterTradingBot()
    
    try:
        # 初始化
        await bot.initialize()
        
        # 执行命令
        if args.command == 'account':
            await bot.show_account_info()
            
        elif args.command == 'risk':
            await bot.show_risk_metrics()
            
        elif args.command == 'market':
            await bot.show_market_data(args.symbol)
            
        elif args.command == 'test':
            await bot.place_test_order(args.symbol)
            
        elif args.command == 'grid':
            await bot.run_grid_strategy(args.symbol)
            
        elif args.command == 'momentum':
            await bot.run_momentum_strategy(args.symbol)
            
        elif args.command == 'arbitrage':
            await bot.run_arbitrage_strategy(args.symbol)
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止...")
        
    except Exception as e:
        logger.error(f"程序错误: {e}")
        
    finally:
        # 清理资源
        await bot.cleanup()


if __name__ == '__main__':
    # 设置日志
    logger.add(
        "lighter_trading.log",
        rotation="1 day",
        retention="7 days",
        level="INFO"
    )
    
    # 运行主程序
    asyncio.run(main())