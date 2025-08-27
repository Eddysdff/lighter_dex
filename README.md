# Lighter DEX Python 交易脚本

基于 Lighter DEX API 的专业级 Python 合约交易系统，提供完整的交易功能、风险管理和多种交易策略。

## 🚀 功能特性

### 核心功能
- **账户管理**: 余额查询、持仓管理、PnL追踪
- **市场数据**: 实时订单簿、K线数据、成交记录
- **交易执行**: 限价单/市价单、批量下单、订单管理
- **风险控制**: 仓位限制、止损止盈、回撤监控
- **WebSocket**: 实时数据推送、订单状态更新

### 交易策略
- **网格交易**: 自动创建价格网格，低买高卖
- **动量策略**: 基于价格动量的趋势跟踪
- **套利策略**: 发现并执行套利机会

## 📋 系统要求

- Python 3.8+
- 稳定的网络连接
- Lighter DEX API密钥

## 🛠️ 安装配置

### 1. 克隆项目
```bash
git clone <repository_url>
cd lighter_dex
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
cp .env.example .env
```

编辑 `.env` 文件，填入您的API配置：
```env
LIGHTER_API_KEY=your_api_key_here
LIGHTER_API_SECRET=your_api_secret_here
LIGHTER_PRIVATE_KEY=your_private_key_here
LIGHTER_NETWORK=testnet  # 或 mainnet
```

## 📚 项目结构

```
lighter_dex/
├── config.py           # 配置管理
├── lighter_client.py   # Lighter API客户端封装
├── risk_manager.py     # 风险管理模块
├── websocket_client.py # WebSocket实时数据
├── strategies.py       # 交易策略实现
├── main.py            # 主程序入口
├── requirements.txt    # 依赖包列表
├── .env.example       # 环境变量示例
└── README.md          # 项目文档
```

## 🎯 使用指南

### 基础命令

#### 查看账户信息
```bash
python main.py account
```

#### 查看风险指标
```bash
python main.py risk
```

#### 查看市场数据
```bash
python main.py market --symbol BTC-USDT
```

#### 下测试订单
```bash
python main.py test --symbol BTC-USDT
```

### 运行交易策略

#### 网格交易策略
```bash
python main.py grid --symbol BTC-USDT
```

#### 动量策略
```bash
python main.py momentum --symbol ETH-USDT
```

#### 套利策略
```bash
python main.py arbitrage --symbol SOL-USDT
```

## 💻 代码示例

### 基础使用
```python
import asyncio
from lighter_client import LighterClient
from config import get_config

async def main():
    # 初始化客户端
    config = get_config()
    client = LighterClient(config)
    
    # 获取账户余额
    balance = await client.get_account_balance()
    print(f"账户余额: ${balance['total_balance']:.2f}")
    
    # 获取市场数据
    orderbook = await client.get_orderbook("BTC-USDT", depth=5)
    print(f"BTC价格: ${orderbook['best_bid']:.2f} / ${orderbook['best_ask']:.2f}")
    
    # 下限价单
    order = await client.place_order(
        symbol="BTC-USDT",
        side="buy",
        order_type="limit",
        quantity=0.01,
        price=50000
    )
    print(f"订单已下: {order}")
    
    # 关闭客户端
    await client.close()

asyncio.run(main())
```

### 使用风险管理
```python
from risk_manager import RiskManager

async def safe_trading():
    client = LighterClient()
    risk_manager = RiskManager(client)
    
    # 检查仓位限制
    passed, reason = await risk_manager.check_position_limits(
        symbol="BTC-USDT",
        side="buy",
        quantity=1.0,
        leverage=10
    )
    
    if passed:
        # 计算合适的仓位大小
        position_size = await risk_manager.calculate_position_size(
            symbol="BTC-USDT",
            risk_amount=100,  # 风险$100
            stop_loss_price=49000,
            entry_price=50000
        )
        
        # 下单并设置止损止盈
        order = await client.place_order(...)
        await risk_manager.set_stop_loss_take_profit(
            symbol="BTC-USDT",
            side="buy",
            entry_price=50000,
            quantity=position_size
        )
```

### 实时数据订阅
```python
from websocket_client import WebSocketClient

async def realtime_data():
    ws_client = WebSocketClient()
    await ws_client.connect()
    
    # 订阅订单簿更新
    async def on_orderbook(data):
        print(f"订单簿更新: {data}")
    
    await ws_client.subscribe_orderbook(
        symbol="BTC-USDT",
        callback=on_orderbook,
        depth=10
    )
    
    # 保持连接
    await asyncio.sleep(3600)
    await ws_client.disconnect()
```

## ⚙️ 配置说明

### 交易配置
- `MAX_POSITION_SIZE`: 最大仓位限制
- `MAX_ORDER_SIZE`: 单笔订单最大数量
- `DEFAULT_LEVERAGE`: 默认杠杆倍数

### 风险管理
- `STOP_LOSS_PERCENTAGE`: 默认止损百分比
- `TAKE_PROFIT_PERCENTAGE`: 默认止盈百分比
- `MAX_DRAWDOWN`: 最大回撤限制

### 网络配置
- `LIGHTER_NETWORK`: 选择主网或测试网
- `LIGHTER_API_URL`: API端点地址
- `LIGHTER_WS_URL`: WebSocket端点地址

## 🔒 安全建议

1. **API密钥安全**
   - 永远不要将API密钥提交到版本控制
   - 使用环境变量或安全的密钥管理服务
   - 定期轮换API密钥

2. **风险控制**
   - 始终设置止损订单
   - 使用适当的仓位大小
   - 监控账户回撤

3. **测试环境**
   - 先在测试网进行充分测试
   - 验证所有策略逻辑
   - 确认风险管理功能正常

4. **生产部署**
   - 使用进程管理器（如systemd或supervisor）
   - 实现错误监控和告警
   - 保持日志记录

## 📊 策略说明

### 网格交易策略
- **原理**: 在价格区间内设置买卖网格，低买高卖
- **适用场景**: 震荡市场
- **参数调整**:
  - `grid_levels`: 网格层数（建议5-20）
  - `grid_spacing`: 网格间距（建议0.5%-2%）

### 动量策略
- **原理**: 跟踪价格动量，顺势交易
- **适用场景**: 趋势市场
- **参数调整**:
  - `lookback_period`: 回望周期（建议10-50）
  - `momentum_threshold`: 动量阈值（建议1%-5%）

### 套利策略
- **原理**: 发现价格差异，执行套利交易
- **适用场景**: 市场非有效时期
- **参数调整**:
  - `spread_threshold`: 价差阈值（建议0.1%-0.5%）

## 🐛 故障排除

### 常见问题

1. **连接失败**
   - 检查网络连接
   - 验证API密钥是否正确
   - 确认API端点地址

2. **订单失败**
   - 检查账户余额
   - 验证订单参数
   - 查看错误日志

3. **WebSocket断线**
   - 系统会自动重连
   - 检查网络稳定性
   - 查看重连日志

### 日志查看
```bash
tail -f lighter_trading.log
```

## 📈 性能优化

1. **批量操作**: 使用批量下单减少API调用
2. **缓存机制**: 缓存常用数据减少重复查询
3. **异步处理**: 充分利用asyncio并发能力
4. **连接池**: 复用WebSocket连接

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License

## 🔗 相关链接

- [Lighter API文档](https://apibetadocs.lighter.xyz/docs/private-beta)
- [Lighter Python SDK](https://github.com/elliottech/lighter-python)

## ⚠️ 免责声明

本软件仅供学习和研究使用。加密货币交易存在高风险，可能导致资金损失。使用本软件进行实际交易前，请充分了解相关风险。作者不对使用本软件造成的任何损失负责。

---

**注意**: 在生产环境使用前，请务必进行充分的测试和风险评估。