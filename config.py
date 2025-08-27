"""
Lighter DEX 交易配置管理
"""
import os
from typing import Optional
from pydantic import BaseSettings, Field, validator
from dotenv import load_dotenv
from enum import Enum

# 加载环境变量
load_dotenv()


class NetworkType(str, Enum):
    """网络类型"""
    MAINNET = "mainnet"
    TESTNET = "testnet"


class TradingConfig(BaseSettings):
    """交易配置"""
    
    # API配置
    api_key: str = Field(..., env="LIGHTER_API_KEY")
    api_secret: Optional[str] = Field(None, env="LIGHTER_API_SECRET")
    private_key: Optional[str] = Field(None, env="LIGHTER_PRIVATE_KEY")
    
    # 网络配置
    network: NetworkType = Field(NetworkType.TESTNET, env="LIGHTER_NETWORK")
    api_url: str = Field("https://api.lighter.xyz", env="LIGHTER_API_URL")
    ws_url: str = Field("wss://ws.lighter.xyz", env="LIGHTER_WS_URL")
    
    # 交易限制
    max_position_size: float = Field(10000, env="MAX_POSITION_SIZE")
    max_order_size: float = Field(1000, env="MAX_ORDER_SIZE")
    default_leverage: int = Field(10, env="DEFAULT_LEVERAGE")
    
    # 风险管理
    stop_loss_percentage: float = Field(5.0, env="STOP_LOSS_PERCENTAGE")
    take_profit_percentage: float = Field(10.0, env="TAKE_PROFIT_PERCENTAGE")
    max_drawdown: float = Field(20.0, env="MAX_DRAWDOWN")
    
    # 日志配置
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_file: str = Field("lighter_trading.log", env="LOG_FILE")
    
    # API限制
    rate_limit_per_second: int = Field(10, description="每秒API请求限制")
    max_retries: int = Field(3, description="API请求最大重试次数")
    timeout: int = Field(30, description="API请求超时时间（秒）")
    
    @validator("network")
    def validate_network(cls, v):
        """验证网络类型"""
        if v not in [NetworkType.MAINNET, NetworkType.TESTNET]:
            raise ValueError(f"Invalid network type: {v}")
        return v
    
    @validator("api_url", "ws_url")
    def validate_urls(cls, v):
        """验证URL格式"""
        if not v.startswith(("http://", "https://", "ws://", "wss://")):
            raise ValueError(f"Invalid URL format: {v}")
        return v
    
    @validator("stop_loss_percentage", "take_profit_percentage", "max_drawdown")
    def validate_percentages(cls, v):
        """验证百分比范围"""
        if not 0 < v <= 100:
            raise ValueError(f"Percentage must be between 0 and 100: {v}")
        return v
    
    @property
    def is_mainnet(self) -> bool:
        """是否为主网"""
        return self.network == NetworkType.MAINNET
    
    @property
    def is_testnet(self) -> bool:
        """是否为测试网"""
        return self.network == NetworkType.TESTNET
    
    class Config:
        """Pydantic配置"""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


class MarketConfig:
    """市场配置"""
    
    # 支持的交易对
    SUPPORTED_PAIRS = [
        "BTC-USDT",
        "ETH-USDT",
        "SOL-USDT",
        "ARB-USDT",
        "OP-USDT"
    ]
    
    # 订单类型
    ORDER_TYPES = {
        "LIMIT": "limit",
        "MARKET": "market",
        "STOP": "stop",
        "STOP_LIMIT": "stop_limit"
    }
    
    # 订单方向
    ORDER_SIDES = {
        "BUY": "buy",
        "SELL": "sell"
    }
    
    # 订单状态
    ORDER_STATUS = {
        "PENDING": "pending",
        "OPEN": "open",
        "PARTIAL": "partial",
        "FILLED": "filled",
        "CANCELLED": "cancelled",
        "REJECTED": "rejected"
    }
    
    # K线时间间隔
    CANDLE_INTERVALS = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1w": 604800
    }
    
    # 精度配置（根据实际市场调整）
    PRECISION = {
        "BTC-USDT": {"price": 2, "quantity": 4},
        "ETH-USDT": {"price": 2, "quantity": 3},
        "SOL-USDT": {"price": 3, "quantity": 2},
        "ARB-USDT": {"price": 4, "quantity": 1},
        "OP-USDT": {"price": 4, "quantity": 1}
    }


# 全局配置实例
try:
    config = TradingConfig()
except Exception as e:
    print(f"警告: 无法加载配置，使用默认值。错误: {e}")
    # 使用默认配置
    config = None


def get_config() -> TradingConfig:
    """获取配置实例"""
    global config
    if config is None:
        raise RuntimeError("配置未初始化，请检查.env文件")
    return config


def reload_config():
    """重新加载配置"""
    global config
    load_dotenv(override=True)
    config = TradingConfig()
    return config