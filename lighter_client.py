"""
Lighter API 客户端封装
提供与Lighter DEX交互的核心功能
"""
import asyncio
import time
import hmac
import hashlib
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import aiohttp
from loguru import logger
from config import config

class OrderType(Enum):
    """订单类型"""
    LIMIT = "limit"
    MARKET = "market"
    LIMIT_MAKER = "limit_maker"  # 只做Maker单

class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class Order:
    """订单数据结构"""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: float
    amount: float
    filled: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    timestamp: int = 0
    fee: float = 0.0

@dataclass
class Balance:
    """账户余额"""
    asset: str
    free: float
    locked: float
    total: float

@dataclass
class Position:
    """持仓信息"""
    symbol: str
    side: str
    amount: float
    entry_price: float
    mark_price: float
    pnl: float
    margin: float

class LighterClient:
    """Lighter API客户端"""
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """初始化客户端"""
        self.api_key = api_key or config.api_key
        self.api_secret = api_secret or config.api_secret
        self.base_url = config.base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.nonce = int(time.time() * 1000)
        
        # 统计数据
        self.total_volume = 0.0
        self.total_trades = 0
        self.total_fees = 0.0
        self.start_time = time.time()
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()
        
    async def connect(self):
        """建立连接"""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("✅ Lighter客户端连接建立")
            
    async def close(self):
        """关闭连接"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("❌ Lighter客户端连接关闭")
            
    def _generate_signature(self, method: str, path: str, params: Dict = None, body: str = "") -> str:
        """生成API签名"""
        timestamp = str(int(time.time() * 1000))
        self.nonce += 1
        nonce = str(self.nonce)
        
        # 构造签名消息
        message_parts = [timestamp, nonce, method.upper(), path]
        
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            message_parts.append(query_string)
            
        if body:
            message_parts.append(body)
            
        message = "\n".join(message_parts)
        
        # 生成HMAC签名
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature, timestamp, nonce
        
    async def _request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Dict:
        """发送API请求"""
        if not self.session:
            await self.connect()
            
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""
        
        # 生成签名
        signature, timestamp, nonce = self._generate_signature(method, endpoint, params, body)
        
        # 构造请求头
        headers = {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-NONCE": nonce,
            "Content-Type": "application/json"
        }
        
        try:
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=body
            ) as response:
                result = await response.json()
                
                if response.status != 200:
                    logger.error(f"API错误 {response.status}: {result}")
                    raise Exception(f"API错误: {result}")
                    
                return result
                
        except Exception as e:
            logger.error(f"请求失败: {e}")
            raise
            
    # ==================== 账户相关 ====================
    
    async def get_balance(self) -> List[Balance]:
        """获取账户余额"""
        result = await self._request("GET", "/account/balance")
        balances = []
        
        for item in result.get("balances", []):
            balances.append(Balance(
                asset=item["asset"],
                free=float(item["free"]),
                locked=float(item["locked"]),
                total=float(item["free"]) + float(item["locked"])
            ))
            
        return balances
        
    async def get_positions(self) -> List[Position]:
        """获取持仓信息"""
        result = await self._request("GET", "/account/positions")
        positions = []
        
        for item in result.get("positions", []):
            positions.append(Position(
                symbol=item["symbol"],
                side=item["side"],
                amount=float(item["amount"]),
                entry_price=float(item["entryPrice"]),
                mark_price=float(item["markPrice"]),
                pnl=float(item["unrealizedPnl"]),
                margin=float(item["margin"])
            ))
            
        return positions
        
    # ==================== 市场数据 ====================
    
    async def get_ticker(self, symbol: str) -> Dict:
        """获取交易对行情"""
        result = await self._request("GET", f"/market/ticker/{symbol}")
        return {
            "symbol": symbol,
            "bid": float(result["bid"]),
            "ask": float(result["ask"]),
            "last": float(result["last"]),
            "volume": float(result["volume24h"]),
            "timestamp": result["timestamp"]
        }
        
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """获取订单簿"""
        params = {"depth": depth}
        result = await self._request("GET", f"/market/orderbook/{symbol}", params=params)
        
        return {
            "bids": [(float(p), float(q)) for p, q in result["bids"]],
            "asks": [(float(p), float(q)) for p, q in result["asks"]],
            "timestamp": result["timestamp"]
        }
        
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取最近成交"""
        params = {"limit": limit}
        result = await self._request("GET", f"/market/trades/{symbol}", params=params)
        
        trades = []
        for trade in result.get("trades", []):
            trades.append({
                "id": trade["id"],
                "price": float(trade["price"]),
                "amount": float(trade["amount"]),
                "side": trade["side"],
                "timestamp": trade["timestamp"]
            })
            
        return trades
        
    # ==================== 交易功能 ====================
    
    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: float,
        price: float = None,
        client_order_id: str = None
    ) -> Order:
        """创建订单"""
        data = {
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "amount": str(amount),
        }
        
        if price and order_type != OrderType.MARKET:
            data["price"] = str(price)
            
        if client_order_id:
            data["clientOrderId"] = client_order_id
            
        # 模拟模式
        if config.dry_run:
            logger.info(f"[模拟] 创建订单: {side.value} {amount} @ {price}")
            return Order(
                id=f"sim_{int(time.time()*1000)}",
                symbol=symbol,
                side=side,
                type=order_type,
                price=price or 0,
                amount=amount,
                status=OrderStatus.FILLED
            )
            
        result = await self._request("POST", "/orders", data=data)
        
        # 更新统计
        self.total_trades += 1
        self.total_volume += amount * (price or 0)
        
        return Order(
            id=result["orderId"],
            symbol=symbol,
            side=side,
            type=order_type,
            price=price or 0,
            amount=amount,
            status=OrderStatus(result["status"]),
            timestamp=result["timestamp"]
        )
        
    async def create_batch_orders(self, orders: List[Dict]) -> List[Order]:
        """批量创建订单"""
        created_orders = []
        
        # Lighter可能有批量接口，这里先用循环实现
        for order_data in orders:
            try:
                order = await self.create_order(**order_data)
                created_orders.append(order)
                await asyncio.sleep(0.1)  # 避免频率限制
            except Exception as e:
                logger.error(f"创建订单失败: {e}")
                continue
                
        return created_orders
        
    async def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """取消订单"""
        if config.dry_run:
            logger.info(f"[模拟] 取消订单: {order_id}")
            return True
            
        try:
            await self._request("DELETE", f"/orders/{order_id}")
            return True
        except Exception as e:
            logger.error(f"取消订单失败 {order_id}: {e}")
            return False
            
    async def cancel_all_orders(self, symbol: str = None) -> int:
        """取消所有订单"""
        if config.dry_run:
            logger.info("[模拟] 取消所有订单")
            return 0
            
        params = {"symbol": symbol} if symbol else {}
        result = await self._request("DELETE", "/orders", params=params)
        return result.get("cancelled", 0)
        
    async def get_order(self, order_id: str) -> Order:
        """获取订单信息"""
        result = await self._request("GET", f"/orders/{order_id}")
        
        return Order(
            id=result["orderId"],
            symbol=result["symbol"],
            side=OrderSide(result["side"]),
            type=OrderType(result["type"]),
            price=float(result["price"]),
            amount=float(result["amount"]),
            filled=float(result["filled"]),
            status=OrderStatus(result["status"]),
            timestamp=result["timestamp"],
            fee=float(result.get("fee", 0))
        )
        
    async def get_open_orders(self, symbol: str = None) -> List[Order]:
        """获取未成交订单"""
        params = {"symbol": symbol} if symbol else {}
        result = await self._request("GET", "/orders/open", params=params)
        
        orders = []
        for item in result.get("orders", []):
            orders.append(Order(
                id=item["orderId"],
                symbol=item["symbol"],
                side=OrderSide(item["side"]),
                type=OrderType(item["type"]),
                price=float(item["price"]),
                amount=float(item["amount"]),
                filled=float(item.get("filled", 0)),
                status=OrderStatus(item["status"]),
                timestamp=item["timestamp"]
            ))
            
        return orders
        
    async def get_trade_history(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """获取成交历史"""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
            
        result = await self._request("GET", "/account/trades", params=params)
        
        trades = []
        for trade in result.get("trades", []):
            trades.append({
                "id": trade["tradeId"],
                "orderId": trade["orderId"],
                "symbol": trade["symbol"],
                "side": trade["side"],
                "price": float(trade["price"]),
                "amount": float(trade["amount"]),
                "fee": float(trade["fee"]),
                "timestamp": trade["timestamp"]
            })
            
        return trades
        
    # ==================== 统计功能 ====================
    
    def get_statistics(self) -> Dict:
        """获取运行统计"""
        runtime = time.time() - self.start_time
        hours = runtime / 3600
        
        return {
            "total_volume": self.total_volume,
            "total_trades": self.total_trades,
            "total_fees": self.total_fees,
            "runtime_hours": hours,
            "avg_volume_per_hour": self.total_volume / hours if hours > 0 else 0,
            "avg_trades_per_hour": self.total_trades / hours if hours > 0 else 0
        }
        
    async def check_api_status(self) -> bool:
        """检查API状态"""
        try:
            result = await self._request("GET", "/system/status")
            return result.get("status") == "ok"
        except:
            return False

# 测试代码
async def test_client():
    """测试客户端功能"""
    async with LighterClient() as client:
        # 检查API状态
        status = await client.check_api_status()
        logger.info(f"API状态: {'正常' if status else '异常'}")
        
        # 获取余额
        balances = await client.get_balance()
        for balance in balances:
            if balance.total > 0:
                logger.info(f"余额 - {balance.asset}: {balance.total:.4f}")
        
        # 获取行情
        ticker = await client.get_ticker(config.symbol)
        logger.info(f"行情 - {config.symbol}: Bid={ticker['bid']:.2f}, Ask={ticker['ask']:.2f}")
        
        # 获取订单簿
        orderbook = await client.get_orderbook(config.symbol, depth=5)
        logger.info(f"买一: {orderbook['bids'][0][0]:.2f}, 卖一: {orderbook['asks'][0][0]:.2f}")

if __name__ == "__main__":
    asyncio.run(test_client())