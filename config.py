"""
Lighter Volume Bot 配置文件
用于刷交易量获取积分的配置参数
"""
import os
from dotenv import load_dotenv
from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum

# 加载环境变量
load_dotenv()

class TradingStrategy(Enum):
    """交易策略枚举"""
    SELF_TRADE = "self_trade"       # 自成交（对敲）
    GRID = "grid"                    # 网格交易
    MARKET_MAKE = "market_make"      # 做市商
    HYBRID = "hybrid"                # 混合策略

@dataclass
class TradingConfig:
    """交易配置"""
    # API配置
    api_key: str = os.getenv("LIGHTER_API_KEY", "")
    api_secret: str = os.getenv("LIGHTER_API_SECRET", "")
    base_url: str = os.getenv("LIGHTER_BASE_URL", "https://api.lighter.xyz/v1")
    ws_url: str = os.getenv("LIGHTER_WS_URL", "wss://api.lighter.xyz/v1/ws")
    
    # 交易对配置
    symbol: str = "ETH-USDT"                # 交易对
    
    # 订单参数
    min_order_size: float = 10.0            # 最小订单量（USDT）
    max_order_size: float = 100.0           # 最大订单量（USDT）
    order_size_variance: float = 0.3        # 订单量随机波动范围（30%）
    
    # 价格参数
    price_offset_bps: int = 10              # 价格偏移基点（0.1%）
    spread_bps: int = 5                     # 买卖价差基点（0.05%）
    
    # 频率控制
    order_interval_seconds: float = 1.0     # 下单间隔（秒）
    batch_size: int = 5                     # 批量下单数量
    cancel_after_seconds: int = 30          # 挂单后多久撤销（秒）
    
    # 交易量目标
    daily_volume_target: float = 100000.0   # 日目标交易量（USDT）
    hourly_volume_target: float = 4200.0    # 小时目标交易量
    
    # 风险控制
    max_daily_loss: float = 50.0            # 最大日亏损（USDT）
    max_position_size: float = 1000.0       # 最大持仓（USDT）
    stop_loss_percent: float = 2.0          # 止损百分比
    max_open_orders: int = 20               # 最大挂单数量
    
    # 策略选择
    strategy: TradingStrategy = TradingStrategy.GRID
    enable_multi_strategy: bool = True      # 启用多策略轮换
    
    # 网格策略参数
    grid_levels: int = 10                   # 网格层数
    grid_spacing_bps: int = 20              # 网格间距基点（0.2%）
    grid_order_size: float = 20.0           # 每层订单量
    
    # 自成交策略参数
    self_trade_enabled: bool = True         # 启用自成交
    self_trade_ratio: float = 0.3           # 自成交占比
    
    # 监控和日志
    enable_monitoring: bool = True          # 启用监控
    log_level: str = "INFO"                 # 日志级别
    stats_interval_seconds: int = 60        # 统计间隔
    
    # 安全设置
    dry_run: bool = False                   # 模拟运行（不真实下单）
    emergency_stop: bool = False            # 紧急停止
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            k: v.value if isinstance(v, Enum) else v 
            for k, v in self.__dict__.items()
        }

# 创建全局配置实例
config = TradingConfig()

# 验证配置
def validate_config():
    """验证配置参数"""
    errors = []
    
    if not config.api_key:
        errors.append("API_KEY未设置")
    if not config.api_secret:
        errors.append("API_SECRET未设置")
    
    if config.min_order_size <= 0:
        errors.append("最小订单量必须大于0")
    
    if config.max_order_size < config.min_order_size:
        errors.append("最大订单量必须大于等于最小订单量")
    
    if config.max_daily_loss <= 0:
        errors.append("最大日亏损必须大于0")
    
    if errors:
        raise ValueError(f"配置错误: {', '.join(errors)}")
    
    return True

# 输出配置信息
def print_config():
    """打印当前配置"""
    from tabulate import tabulate
    
    config_items = [
        ["策略", config.strategy.value],
        ["交易对", config.symbol],
        ["订单量", f"{config.min_order_size}-{config.max_order_size} USDT"],
        ["日目标交易量", f"{config.daily_volume_target:,.0f} USDT"],
        ["最大日亏损", f"{config.max_daily_loss} USDT"],
        ["最大持仓", f"{config.max_position_size} USDT"],
        ["网格层数", config.grid_levels if config.strategy == TradingStrategy.GRID else "N/A"],
        ["模拟模式", "是" if config.dry_run else "否"],
    ]
    
    print("\n" + "="*50)
    print("🤖 Lighter Volume Bot 配置")
    print("="*50)
    print(tabulate(config_items, headers=["参数", "值"], tablefmt="grid"))
    print("="*50 + "\n")

if __name__ == "__main__":
    validate_config()
    print_config()