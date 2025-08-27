"""
Lighter DEX 客户端封装
提供与Lighter API交互的高级接口
"""
import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
from loguru import logger
import lighter
from lighter.api_client import ApiClient
from lighter.configuration import Configuration
from lighter.api import (
    AccountApi, 
    OrderApi, 
    TransactionApi,
    CandlestickApi,
    BlockApi
)
from config import get_config, MarketConfig


class LighterClient:
    """Lighter DEX 客户端"""
    
    def __init__(self, config=None):
        """
        初始化客户端
        
        Args:
            config: 配置对象，如果为None则使用默认配置
        """
        self.config = config or get_config()
        self._setup_client()
        self._setup_logger()
        
        # API实例
        self.account_api = AccountApi(self.api_client)
        self.order_api = OrderApi(self.api_client)
        self.transaction_api = TransactionApi(self.api_client)
        self.candlestick_api = CandlestickApi(self.api_client)
        self.block_api = BlockApi(self.api_client)
        
        # 缓存
        self._account_cache = {}
        self._order_cache = {}
        self._last_nonce = None
        
    def _setup_client(self):
        """设置API客户端"""
        configuration = Configuration()
        configuration.host = self.config.api_url
        
        # 设置API密钥
        if self.config.api_key:
            configuration.api_key['ApiKeyAuth'] = self.config.api_key
        
        # 设置超时
        configuration.timeout = self.config.timeout
        
        self.api_client = ApiClient(configuration)
        
    def _setup_logger(self):
        """设置日志"""
        logger.add(
            self.config.log_file,
            rotation="1 day",
            retention="7 days",
            level=self.config.log_level
        )
        
    # ==================== 账户管理 ====================
    
    async def get_account_info(self, address: Optional[str] = None) -> Dict:
        """
        获取账户信息
        
        Args:
            address: 账户地址，如果为None则使用配置中的地址
            
        Returns:
            账户信息字典
        """
        try:
            if not address:
                # 从私钥或API密钥推导地址
                address = self._get_default_address()
            
            response = await self.account_api.account(address=address)
            self._account_cache[address] = response
            logger.info(f"获取账户信息成功: {address}")
            return response
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            raise
            
    async def get_account_positions(self, address: Optional[str] = None) -> List[Dict]:
        """
        获取账户持仓
        
        Args:
            address: 账户地址
            
        Returns:
            持仓列表
        """
        try:
            account_info = await self.get_account_info(address)
            positions = account_info.get('positions', [])
            
            # 格式化持仓数据
            formatted_positions = []
            for pos in positions:
                formatted_positions.append({
                    'symbol': pos.get('symbol'),
                    'side': pos.get('side'),
                    'size': float(pos.get('size', 0)),
                    'entry_price': float(pos.get('entryPrice', 0)),
                    'mark_price': float(pos.get('markPrice', 0)),
                    'unrealized_pnl': float(pos.get('unrealizedPnl', 0)),
                    'margin': float(pos.get('margin', 0)),
                    'leverage': pos.get('leverage', 1)
                })
                
            logger.info(f"获取到 {len(formatted_positions)} 个持仓")
            return formatted_positions
            
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            raise
            
    async def get_account_balance(self, address: Optional[str] = None) -> Dict:
        """
        获取账户余额
        
        Args:
            address: 账户地址
            
        Returns:
            余额信息
        """
        try:
            account_info = await self.get_account_info(address)
            
            balance = {
                'total_balance': float(account_info.get('totalBalance', 0)),
                'available_balance': float(account_info.get('availableBalance', 0)),
                'margin_balance': float(account_info.get('marginBalance', 0)),
                'unrealized_pnl': float(account_info.get('unrealizedPnl', 0)),
                'realized_pnl': float(account_info.get('realizedPnl', 0))
            }
            
            logger.info(f"账户余额: {balance}")
            return balance
            
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            raise
            
    async def get_pnl_history(
        self, 
        address: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        获取PnL历史
        
        Args:
            address: 账户地址
            start_time: 开始时间
            end_time: 结束时间
            
        Returns:
            PnL历史DataFrame
        """
        try:
            if not address:
                address = self._get_default_address()
                
            # 设置默认时间范围
            if not end_time:
                end_time = datetime.now()
            if not start_time:
                start_time = end_time - timedelta(days=7)
                
            response = await self.account_api.pnl(
                address=address,
                start=int(start_time.timestamp()),
                end=int(end_time.timestamp())
            )
            
            # 转换为DataFrame
            df = pd.DataFrame(response.get('pnl', []))
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('timestamp', inplace=True)
                
            logger.info(f"获取到 {len(df)} 条PnL记录")
            return df
            
        except Exception as e:
            logger.error(f"获取PnL历史失败: {e}")
            raise
            
    # ==================== 市场数据 ====================
    
    async def get_orderbook(
        self, 
        symbol: str, 
        depth: int = 20
    ) -> Dict:
        """
        获取订单簿
        
        Args:
            symbol: 交易对
            depth: 深度
            
        Returns:
            订单簿数据
        """
        try:
            response = await self.order_api.order_book_details(
                symbol=symbol,
                depth=depth
            )
            
            orderbook = {
                'symbol': symbol,
                'timestamp': datetime.now(),
                'bids': response.get('bids', []),
                'asks': response.get('asks', []),
                'best_bid': float(response['bids'][0][0]) if response.get('bids') else None,
                'best_ask': float(response['asks'][0][0]) if response.get('asks') else None,
                'spread': None
            }
            
            # 计算价差
            if orderbook['best_bid'] and orderbook['best_ask']:
                orderbook['spread'] = orderbook['best_ask'] - orderbook['best_bid']
                
            logger.debug(f"获取订单簿成功: {symbol}")
            return orderbook
            
        except Exception as e:
            logger.error(f"获取订单簿失败: {e}")
            raise
            
    async def get_recent_trades(
        self, 
        symbol: str, 
        limit: int = 100
    ) -> List[Dict]:
        """
        获取最近成交
        
        Args:
            symbol: 交易对
            limit: 数量限制
            
        Returns:
            成交列表
        """
        try:
            response = await self.order_api.recent_trades(
                symbol=symbol,
                limit=limit
            )
            
            trades = []
            for trade in response.get('trades', []):
                trades.append({
                    'id': trade.get('id'),
                    'symbol': symbol,
                    'price': float(trade.get('price', 0)),
                    'quantity': float(trade.get('quantity', 0)),
                    'side': trade.get('side'),
                    'timestamp': pd.to_datetime(trade.get('timestamp'), unit='s')
                })
                
            logger.debug(f"获取到 {len(trades)} 条成交记录")
            return trades
            
        except Exception as e:
            logger.error(f"获取成交记录失败: {e}")
            raise
            
    async def get_candlesticks(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        获取K线数据
        
        Args:
            symbol: 交易对
            interval: 时间间隔
            start_time: 开始时间
            end_time: 结束时间
            limit: 数量限制
            
        Returns:
            K线数据DataFrame
        """
        try:
            # 验证时间间隔
            if interval not in MarketConfig.CANDLE_INTERVALS:
                raise ValueError(f"不支持的时间间隔: {interval}")
                
            # 设置默认时间范围
            if not end_time:
                end_time = datetime.now()
            if not start_time:
                interval_seconds = MarketConfig.CANDLE_INTERVALS[interval]
                start_time = end_time - timedelta(seconds=interval_seconds * limit)
                
            response = await self.candlestick_api.candlesticks(
                symbol=symbol,
                interval=interval,
                start=int(start_time.timestamp()),
                end=int(end_time.timestamp()),
                limit=limit
            )
            
            # 转换为DataFrame
            df = pd.DataFrame(response.get('candlesticks', []))
            if not df.empty:
                df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('timestamp', inplace=True)
                df = df.astype(float)
                
            logger.info(f"获取到 {len(df)} 条K线数据")
            return df
            
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            raise
            
    # ==================== 交易功能 ====================
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False
    ) -> Dict:
        """
        下单
        
        Args:
            symbol: 交易对
            side: 方向 (buy/sell)
            order_type: 订单类型 (limit/market/stop/stop_limit)
            quantity: 数量
            price: 价格（限价单必需）
            stop_price: 止损价格（止损单必需）
            client_order_id: 客户端订单ID
            time_in_force: 有效时间类型
            reduce_only: 是否只减仓
            
        Returns:
            订单信息
        """
        try:
            # 验证参数
            if side not in MarketConfig.ORDER_SIDES.values():
                raise ValueError(f"无效的订单方向: {side}")
            if order_type not in MarketConfig.ORDER_TYPES.values():
                raise ValueError(f"无效的订单类型: {order_type}")
                
            # 检查仓位限制
            if quantity > self.config.max_order_size:
                raise ValueError(f"订单数量超过限制: {quantity} > {self.config.max_order_size}")
                
            # 构建订单参数
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': str(quantity),
                'timeInForce': time_in_force,
                'reduceOnly': reduce_only
            }
            
            # 添加价格参数
            if order_type in ['limit', 'stop_limit'] and price is not None:
                order_params['price'] = str(price)
            if order_type in ['stop', 'stop_limit'] and stop_price is not None:
                order_params['stopPrice'] = str(stop_price)
            if client_order_id:
                order_params['clientOrderId'] = client_order_id
                
            # 获取nonce
            nonce = await self._get_next_nonce()
            order_params['nonce'] = nonce
            
            # 发送订单
            response = await self.transaction_api.send_tx(body=order_params)
            
            # 缓存订单
            order_id = response.get('orderId')
            if order_id:
                self._order_cache[order_id] = response
                
            logger.info(f"下单成功: {order_id} - {symbol} {side} {quantity} @ {price}")
            return response
            
        except Exception as e:
            logger.error(f"下单失败: {e}")
            raise
            
    async def cancel_order(
        self,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> Dict:
        """
        取消订单
        
        Args:
            order_id: 订单ID
            client_order_id: 客户端订单ID
            symbol: 交易对
            
        Returns:
            取消结果
        """
        try:
            if not order_id and not client_order_id:
                raise ValueError("必须提供order_id或client_order_id")
                
            # 构建取消参数
            cancel_params = {
                'type': 'cancel_order',
                'nonce': await self._get_next_nonce()
            }
            
            if order_id:
                cancel_params['orderId'] = order_id
            if client_order_id:
                cancel_params['clientOrderId'] = client_order_id
            if symbol:
                cancel_params['symbol'] = symbol
                
            # 发送取消请求
            response = await self.transaction_api.send_tx(body=cancel_params)
            
            # 更新缓存
            if order_id and order_id in self._order_cache:
                self._order_cache[order_id]['status'] = 'cancelled'
                
            logger.info(f"取消订单成功: {order_id or client_order_id}")
            return response
            
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            raise
            
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        取消所有订单
        
        Args:
            symbol: 交易对，如果为None则取消所有交易对的订单
            
        Returns:
            取消结果列表
        """
        try:
            # 获取所有未完成订单
            open_orders = await self.get_open_orders(symbol)
            
            if not open_orders:
                logger.info("没有需要取消的订单")
                return []
                
            # 批量取消
            results = []
            for order in open_orders:
                try:
                    result = await self.cancel_order(order_id=order['id'])
                    results.append(result)
                except Exception as e:
                    logger.warning(f"取消订单失败 {order['id']}: {e}")
                    
            logger.info(f"批量取消 {len(results)} 个订单")
            return results
            
        except Exception as e:
            logger.error(f"批量取消订单失败: {e}")
            raise
            
    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
        address: Optional[str] = None
    ) -> List[Dict]:
        """
        获取未完成订单
        
        Args:
            symbol: 交易对
            address: 账户地址
            
        Returns:
            订单列表
        """
        try:
            if not address:
                address = self._get_default_address()
                
            # 获取账户订单
            account_info = await self.get_account_info(address)
            all_orders = account_info.get('orders', [])
            
            # 筛选未完成订单
            open_orders = []
            for order in all_orders:
                if order.get('status') in ['open', 'partial', 'pending']:
                    if not symbol or order.get('symbol') == symbol:
                        open_orders.append({
                            'id': order.get('id'),
                            'symbol': order.get('symbol'),
                            'side': order.get('side'),
                            'type': order.get('type'),
                            'price': float(order.get('price', 0)),
                            'quantity': float(order.get('quantity', 0)),
                            'filled': float(order.get('filled', 0)),
                            'status': order.get('status'),
                            'timestamp': pd.to_datetime(order.get('timestamp'), unit='s')
                        })
                        
            logger.info(f"获取到 {len(open_orders)} 个未完成订单")
            return open_orders
            
        except Exception as e:
            logger.error(f"获取未完成订单失败: {e}")
            raise
            
    # ==================== 批量交易 ====================
    
    async def place_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        """
        批量下单
        
        Args:
            orders: 订单列表
            
        Returns:
            订单结果列表
        """
        try:
            # 验证订单数量
            if len(orders) > 10:
                raise ValueError("批量订单数量不能超过10个")
                
            # 准备批量订单
            batch_orders = []
            for order in orders:
                order_params = {
                    'symbol': order['symbol'],
                    'side': order['side'],
                    'type': order.get('type', 'limit'),
                    'quantity': str(order['quantity']),
                    'price': str(order.get('price', 0)),
                    'timeInForce': order.get('time_in_force', 'GTC'),
                    'nonce': await self._get_next_nonce()
                }
                batch_orders.append(order_params)
                
            # 发送批量订单
            response = await self.transaction_api.send_tx_batch(body={'orders': batch_orders})
            
            logger.info(f"批量下单成功: {len(batch_orders)} 个订单")
            return response.get('orders', [])
            
        except Exception as e:
            logger.error(f"批量下单失败: {e}")
            raise
            
    # ==================== 辅助方法 ====================
    
    def _get_default_address(self) -> str:
        """获取默认地址"""
        # 这里需要根据实际情况实现地址推导
        # 可能从私钥、API密钥或配置中获取
        return self.config.api_key[:42] if self.config.api_key else None
        
    async def _get_next_nonce(self) -> int:
        """获取下一个nonce"""
        try:
            response = await self.transaction_api.next_nonce(
                address=self._get_default_address()
            )
            nonce = response.get('nonce', 0)
            self._last_nonce = nonce
            return nonce
        except Exception as e:
            logger.error(f"获取nonce失败: {e}")
            # 使用本地计数作为后备
            if self._last_nonce is not None:
                self._last_nonce += 1
                return self._last_nonce
            raise
            
    def format_price(self, price: float, symbol: str) -> str:
        """格式化价格"""
        precision = MarketConfig.PRECISION.get(symbol, {}).get('price', 2)
        return f"{price:.{precision}f}"
        
    def format_quantity(self, quantity: float, symbol: str) -> str:
        """格式化数量"""
        precision = MarketConfig.PRECISION.get(symbol, {}).get('quantity', 4)
        return f"{quantity:.{precision}f}"
        
    async def close(self):
        """关闭客户端"""
        if hasattr(self, 'api_client'):
            await self.api_client.close()
        logger.info("Lighter客户端已关闭")