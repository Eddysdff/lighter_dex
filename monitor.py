"""
监控和统计模块
实时追踪交易量、积分、成本等关键指标
"""
import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
from loguru import logger
from tabulate import tabulate
from colorama import Fore, Style, init

# 初始化colorama
init(autoreset=True)

@dataclass
class TradingMetrics:
    """交易指标"""
    timestamp: float
    total_volume: float          # 总交易量
    total_trades: int            # 总交易次数
    total_fees: float           # 总手续费
    realized_pnl: float         # 已实现盈亏
    unrealized_pnl: float       # 未实现盈亏
    win_rate: float            # 胜率
    avg_trade_size: float       # 平均交易量
    volume_per_hour: float      # 每小时交易量
    estimated_points: float     # 预估积分
    
class VolumeMonitor:
    """交易量监控器"""
    
    def __init__(self):
        self.start_time = time.time()
        self.metrics_history = deque(maxlen=1440)  # 保存24小时数据（每分钟一个点）
        self.hourly_volumes = deque(maxlen=24)     # 24小时交易量
        self.daily_volumes = deque(maxlen=30)      # 30天交易量
        
        # 当前统计
        self.current_metrics = TradingMetrics(
            timestamp=time.time(),
            total_volume=0,
            total_trades=0,
            total_fees=0,
            realized_pnl=0,
            unrealized_pnl=0,
            win_rate=0,
            avg_trade_size=0,
            volume_per_hour=0,
            estimated_points=0
        )
        
        # 积分计算参数（根据Lighter规则调整）
        self.points_per_volume = 0.1  # 每1000 USDT交易量获得0.1积分
        self.maker_bonus = 1.5        # Maker订单积分加成
        self.taker_penalty = 0.8      # Taker订单积分折扣
        
        # 目标追踪
        self.daily_target = 100000    # 日交易量目标
        self.points_target = 100      # 日积分目标
        
    def update_trade(self, volume: float, fee: float, is_maker: bool = False, pnl: float = 0):
        """更新交易数据"""
        self.current_metrics.total_volume += volume
        self.current_metrics.total_trades += 1
        self.current_metrics.total_fees += fee
        self.current_metrics.realized_pnl += pnl
        
        # 计算平均值
        if self.current_metrics.total_trades > 0:
            self.current_metrics.avg_trade_size = (
                self.current_metrics.total_volume / self.current_metrics.total_trades
            )
            
        # 计算每小时交易量
        runtime_hours = (time.time() - self.start_time) / 3600
        if runtime_hours > 0:
            self.current_metrics.volume_per_hour = (
                self.current_metrics.total_volume / runtime_hours
            )
            
        # 估算积分
        points = volume / 1000 * self.points_per_volume
        if is_maker:
            points *= self.maker_bonus
        else:
            points *= self.taker_penalty
            
        self.current_metrics.estimated_points += points
        
    def get_progress(self) -> Dict:
        """获取进度"""
        runtime = time.time() - self.start_time
        hours_elapsed = runtime / 3600
        hours_remaining = 24 - hours_elapsed
        
        # 计算完成度
        volume_progress = (self.current_metrics.total_volume / self.daily_target) * 100
        points_progress = (self.current_metrics.estimated_points / self.points_target) * 100
        
        # 预估完成时间
        if self.current_metrics.volume_per_hour > 0:
            volume_eta = (self.daily_target - self.current_metrics.total_volume) / self.current_metrics.volume_per_hour
            points_eta = (self.points_target - self.current_metrics.estimated_points) / (self.current_metrics.estimated_points / hours_elapsed) if hours_elapsed > 0 else 999
        else:
            volume_eta = points_eta = 999
            
        return {
            "runtime_hours": round(hours_elapsed, 2),
            "volume_progress": round(volume_progress, 2),
            "points_progress": round(points_progress, 2),
            "volume_eta_hours": round(min(volume_eta, hours_remaining), 2),
            "points_eta_hours": round(min(points_eta, hours_remaining), 2),
            "on_track": volume_progress >= (hours_elapsed / 24 * 100)
        }
        
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        metrics = asdict(self.current_metrics)
        progress = self.get_progress()
        
        # 计算效率指标
        efficiency = {
            "cost_per_volume": self.current_metrics.total_fees / self.current_metrics.total_volume * 100 if self.current_metrics.total_volume > 0 else 0,
            "net_result": self.current_metrics.realized_pnl - self.current_metrics.total_fees,
            "points_per_dollar": self.current_metrics.estimated_points / self.current_metrics.total_fees if self.current_metrics.total_fees > 0 else 0,
            "trades_per_minute": self.current_metrics.total_trades / (progress["runtime_hours"] * 60) if progress["runtime_hours"] > 0 else 0
        }
        
        return {
            **metrics,
            **progress,
            **efficiency
        }
        
    def print_dashboard(self):
        """打印仪表板"""
        stats = self.get_statistics()
        
        # 清屏（可选）
        # print("\033[2J\033[H")
        
        print("\n" + "="*80)
        print(f"{Fore.CYAN}📊 Lighter Volume Bot 实时监控 {Style.RESET_ALL}")
        print("="*80)
        
        # 基础统计
        basic_stats = [
            ["⏱️ 运行时间", f"{stats['runtime_hours']:.2f} 小时"],
            ["📈 总交易量", f"{Fore.GREEN}{stats['total_volume']:,.2f} USDT{Style.RESET_ALL}"],
            ["🔄 交易次数", f"{stats['total_trades']} 笔"],
            ["💰 总手续费", f"{Fore.RED}{stats['total_fees']:.4f} USDT{Style.RESET_ALL}"],
            ["📊 平均单笔", f"{stats['avg_trade_size']:.2f} USDT"],
            ["⚡ 每小时量", f"{stats['volume_per_hour']:,.2f} USDT/h"],
        ]
        
        print(tabulate(basic_stats, tablefmt="fancy_grid"))
        
        # 积分和进度
        print(f"\n{Fore.YELLOW}🎯 目标进度{Style.RESET_ALL}")
        
        # 交易量进度条
        volume_progress = stats['volume_progress']
        volume_bar = self._create_progress_bar(volume_progress)
        print(f"交易量: {volume_bar} {volume_progress:.1f}% ({stats['total_volume']:,.0f}/{self.daily_target:,.0f} USDT)")
        
        # 积分进度条
        points_progress = stats['points_progress']
        points_bar = self._create_progress_bar(points_progress)
        print(f"积分数: {points_bar} {points_progress:.1f}% ({stats['estimated_points']:.1f}/{self.points_target} 分)")
        
        # 预计完成时间
        if stats['on_track']:
            status_color = Fore.GREEN
            status_text = "✅ 进度正常"
        else:
            status_color = Fore.YELLOW
            status_text = "⚠️ 进度落后"
            
        print(f"\n{status_color}{status_text}{Style.RESET_ALL}")
        print(f"预计完成: 交易量 {stats['volume_eta_hours']:.1f}h | 积分 {stats['points_eta_hours']:.1f}h")
        
        # 效率指标
        print(f"\n{Fore.MAGENTA}💡 效率分析{Style.RESET_ALL}")
        efficiency_stats = [
            ["成本率", f"{stats['cost_per_volume']:.3f}%"],
            ["净结果", f"{stats['net_result']:.4f} USDT"],
            ["积分/费用", f"{stats['points_per_dollar']:.2f}"],
            ["交易频率", f"{stats['trades_per_minute']:.1f} 笔/分钟"],
        ]
        
        print(tabulate(efficiency_stats, tablefmt="simple"))
        
        # 盈亏统计
        total_pnl = stats['realized_pnl'] + stats['unrealized_pnl']
        pnl_color = Fore.GREEN if total_pnl >= 0 else Fore.RED
        
        print(f"\n{Fore.BLUE}💼 盈亏统计{Style.RESET_ALL}")
        print(f"已实现: {stats['realized_pnl']:.4f} USDT")
        print(f"未实现: {stats['unrealized_pnl']:.4f} USDT")
        print(f"总盈亏: {pnl_color}{total_pnl:.4f} USDT{Style.RESET_ALL}")
        
        print("="*80 + "\n")
        
    def _create_progress_bar(self, percentage: float, width: int = 30) -> str:
        """创建进度条"""
        filled = int(width * min(percentage, 100) / 100)
        bar = "█" * filled + "░" * (width - filled)
        
        if percentage >= 100:
            color = Fore.GREEN
        elif percentage >= 70:
            color = Fore.YELLOW
        else:
            color = Fore.RED
            
        return f"{color}{bar}{Style.RESET_ALL}"
        
    def save_metrics(self, filepath: str = "metrics.json"):
        """保存指标到文件"""
        metrics = asdict(self.current_metrics)
        metrics['timestamp'] = datetime.now().isoformat()
        
        try:
            with open(filepath, 'a') as f:
                json.dump(metrics, f)
                f.write('\n')
        except Exception as e:
            logger.error(f"保存指标失败: {e}")
            
    def alert_check(self) -> List[str]:
        """检查告警条件"""
        alerts = []
        stats = self.get_statistics()
        
        # 检查进度
        if not stats['on_track'] and stats['runtime_hours'] > 1:
            alerts.append("⚠️ 交易量进度落后于预期")
            
        # 检查成本
        if stats['cost_per_volume'] > 0.15:  # 成本超过0.15%
            alerts.append("⚠️ 交易成本过高")
            
        # 检查亏损
        if stats['net_result'] < -10:  # 净亏损超过10 USDT
            alerts.append("🚨 净亏损超过阈值")
            
        # 检查交易频率
        if stats['trades_per_minute'] < 0.5 and stats['runtime_hours'] > 0.5:
            alerts.append("⚠️ 交易频率过低")
            
        return alerts

class PerformanceAnalyzer:
    """性能分析器"""
    
    def __init__(self, monitor: VolumeMonitor):
        self.monitor = monitor
        self.best_hour = None
        self.worst_hour = None
        self.peak_volume = 0
        self.suggestions = []
        
    def analyze(self) -> Dict:
        """分析性能"""
        stats = self.monitor.get_statistics()
        
        # 分析最佳/最差时段
        if self.monitor.hourly_volumes:
            volumes = list(self.monitor.hourly_volumes)
            self.best_hour = volumes.index(max(volumes))
            self.worst_hour = volumes.index(min(volumes))
            self.peak_volume = max(volumes)
            
        # 生成建议
        self.suggestions = self._generate_suggestions(stats)
        
        return {
            "best_hour": self.best_hour,
            "worst_hour": self.worst_hour,
            "peak_volume": self.peak_volume,
            "suggestions": self.suggestions,
            "efficiency_score": self._calculate_efficiency_score(stats)
        }
        
    def _generate_suggestions(self, stats: Dict) -> List[str]:
        """生成优化建议"""
        suggestions = []
        
        # 成本优化
        if stats['cost_per_volume'] > 0.12:
            suggestions.append("📌 建议: 增加Maker订单比例以降低手续费")
            
        # 交易量优化
        if stats['volume_per_hour'] < self.monitor.daily_target / 24:
            suggestions.append("📌 建议: 提高交易频率或增加订单量")
            
        # 策略优化
        if stats['trades_per_minute'] > 5:
            suggestions.append("📌 建议: 考虑增加单笔交易量，减少交易次数")
            
        # 风险控制
        if stats['net_result'] < -5:
            suggestions.append("📌 建议: 检查策略参数，优化价格偏移")
            
        return suggestions
        
    def _calculate_efficiency_score(self, stats: Dict) -> float:
        """计算效率评分（0-100）"""
        score = 100
        
        # 成本扣分
        score -= min(stats['cost_per_volume'] * 100, 30)
        
        # 进度加分
        if stats['on_track']:
            score += 10
            
        # 盈亏影响
        if stats['net_result'] > 0:
            score += 5
        else:
            score -= min(abs(stats['net_result']), 20)
            
        return max(0, min(100, score))

# 实时监控循环
async def monitoring_loop(monitor: VolumeMonitor, interval: int = 60):
    """监控循环"""
    analyzer = PerformanceAnalyzer(monitor)
    
    while True:
        try:
            # 打印仪表板
            monitor.print_dashboard()
            
            # 检查告警
            alerts = monitor.alert_check()
            if alerts:
                print(f"{Fore.YELLOW}⚠️ 告警信息:{Style.RESET_ALL}")
                for alert in alerts:
                    print(f"  {alert}")
                    
            # 性能分析
            if monitor.current_metrics.total_trades > 0 and monitor.current_metrics.total_trades % 100 == 0:
                analysis = analyzer.analyze()
                print(f"\n{Fore.CYAN}🔍 性能分析:{Style.RESET_ALL}")
                print(f"效率评分: {analysis['efficiency_score']:.1f}/100")
                
                if analysis['suggestions']:
                    print("优化建议:")
                    for suggestion in analysis['suggestions']:
                        print(f"  {suggestion}")
                        
            # 保存指标
            if monitor.current_metrics.total_trades % 10 == 0:
                monitor.save_metrics()
                
            await asyncio.sleep(interval)
            
        except KeyboardInterrupt:
            logger.info("监控停止")
            break
        except Exception as e:
            logger.error(f"监控错误: {e}")
            await asyncio.sleep(interval)

# 测试代码
async def test_monitor():
    """测试监控器"""
    monitor = VolumeMonitor()
    
    # 模拟交易
    for i in range(10):
        monitor.update_trade(
            volume=1000 + i * 100,
            fee=1.5,
            is_maker=i % 2 == 0,
            pnl=random.uniform(-1, 2)
        )
        
    monitor.print_dashboard()
    
    # 测试告警
    alerts = monitor.alert_check()
    print(f"告警: {alerts}")

if __name__ == "__main__":
    import random
    asyncio.run(test_monitor())