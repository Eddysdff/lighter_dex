"""
WebSocket客户端
提供实时数据订阅和推送功能
"""
import asyncio
import json
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import websockets
from loguru import logger
from config import get_config


class WebSocketClient:
    """WebSocket客户端"""
    
    def __init__(self, config=None):
        """
        初始化WebSocket客户端
        
        Args:
            config: 配置对象
        """
        self.config = config or get_config()
        self.ws_url = self.config.ws_url
        self.websocket = None
        self.is_connected = False
        
        # 订阅管理
        self.subscriptions = {}
        self.callbacks = {}
        
        # 心跳
        self.heartbeat_interval = 30
        self.last_heartbeat = None
        
        # 重连
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        
    async def connect(self):
        """连接WebSocket"""
        try:
            logger.info(f"连接WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=self.heartbeat_interval,
                ping_timeout=10
            )
            self.is_connected = True
            self.reconnect_attempts = 0
            
            # 启动消息处理
            asyncio.create_task(self._message_handler())
            
            # 启动心跳
            asyncio.create_task(self._heartbeat_loop())
            
            logger.info("WebSocket连接成功")
            
            # 重新订阅
            await self._resubscribe()
            
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            await self._handle_disconnect()
            
    async def disconnect(self):
        """断开WebSocket连接"""
        try:
            self.is_connected = False
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            logger.info("WebSocket已断开")
        except Exception as e:
            logger.error(f"断开WebSocket失败: {e}")
            
    async def _message_handler(self):
        """处理接收的消息"""
        try:
            while self.is_connected and self.websocket:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=60
                    )
                    
                    # 解析消息
                    data = json.loads(message)
                    await self._process_message(data)
                    
                except asyncio.TimeoutError:
                    logger.warning("WebSocket接收超时")
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket连接已关闭")
                    break
                except Exception as e:
                    logger.error(f"处理WebSocket消息失败: {e}")
                    
        except Exception as e:
            logger.error(f"消息处理器错误: {e}")
        finally:
            await self._handle_disconnect()
            
    async def _process_message(self, data: Dict):
        """
        处理消息
        
        Args:
            data: 消息数据
        """
        try:
            msg_type = data.get('type')
            channel = data.get('channel')
            
            # 处理不同类型的消息
            if msg_type == 'ping':
                await self._send_pong()
            elif msg_type == 'error':
                logger.error(f"WebSocket错误: {data.get('message')}")
            elif msg_type == 'subscribed':
                logger.info(f"订阅成功: {channel}")
            elif msg_type == 'unsubscribed':
                logger.info(f"取消订阅: {channel}")
            else:
                # 调用回调函数
                if channel in self.callbacks:
                    for callback in self.callbacks[channel]:
                        try:
                            await callback(data)
                        except Exception as e:
                            logger.error(f"回调函数执行失败: {e}")
                            
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self.is_connected:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                if self.websocket:
                    await self.websocket.ping()
                    self.last_heartbeat = time.time()
                    
            except Exception as e:
                logger.error(f"心跳失败: {e}")
                await self._handle_disconnect()
                break
                
    async def _send_pong(self):
        """发送pong响应"""
        try:
            if self.websocket:
                await self.websocket.send(json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.error(f"发送pong失败: {e}")
            
    async def _handle_disconnect(self):
        """处理断线"""
        self.is_connected = False
        
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            logger.info(f"尝试重连 ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
            
            await asyncio.sleep(self.reconnect_delay * self.reconnect_attempts)
            await self.connect()
        else:
            logger.error("WebSocket重连失败，已达到最大尝试次数")
            
    async def _resubscribe(self):
        """重新订阅所有频道"""
        for channel in self.subscriptions.keys():
            await self._send_subscribe(channel, self.subscriptions[channel])
            
    async def _send_subscribe(self, channel: str, params: Dict):
        """
        发送订阅消息
        
        Args:
            channel: 频道名称
            params: 订阅参数
        """
        try:
            if self.websocket:
                message = {
                    'type': 'subscribe',
                    'channel': channel,
                    **params
                }
                await self.websocket.send(json.dumps(message))
                logger.debug(f"发送订阅: {channel}")
        except Exception as e:
            logger.error(f"发送订阅失败: {e}")
            
    async def _send_unsubscribe(self, channel: str):
        """
        发送取消订阅消息
        
        Args:
            channel: 频道名称
        """
        try:
            if self.websocket:
                message = {
                    'type': 'unsubscribe',
                    'channel': channel
                }
                await self.websocket.send(json.dumps(message))
                logger.debug(f"发送取消订阅: {channel}")
        except Exception as e:
            logger.error(f"发送取消订阅失败: {e}")
            
    # ==================== 订阅接口 ====================
    
    async def subscribe_orderbook(
        self,
        symbol: str,
        callback: Callable,
        depth: int = 20
    ):
        """
        订阅订单簿
        
        Args:
            symbol: 交易对
            callback: 回调函数
            depth: 深度
        """
        channel = f"orderbook.{symbol}"
        params = {'symbol': symbol, 'depth': depth}
        
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅订单簿: {symbol}")
        
    async def subscribe_trades(
        self,
        symbol: str,
        callback: Callable
    ):
        """
        订阅成交数据
        
        Args:
            symbol: 交易对
            callback: 回调函数
        """
        channel = f"trades.{symbol}"
        params = {'symbol': symbol}
        
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅成交数据: {symbol}")
        
    async def subscribe_candlesticks(
        self,
        symbol: str,
        interval: str,
        callback: Callable
    ):
        """
        订阅K线数据
        
        Args:
            symbol: 交易对
            interval: 时间间隔
            callback: 回调函数
        """
        channel = f"candlesticks.{symbol}.{interval}"
        params = {'symbol': symbol, 'interval': interval}
        
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅K线数据: {symbol} {interval}")
        
    async def subscribe_account(
        self,
        address: str,
        callback: Callable
    ):
        """
        订阅账户更新
        
        Args:
            address: 账户地址
            callback: 回调函数
        """
        channel = f"account.{address}"
        params = {'address': address}
        
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅账户更新: {address}")
        
    async def subscribe_orders(
        self,
        address: str,
        callback: Callable,
        symbol: Optional[str] = None
    ):
        """
        订阅订单更新
        
        Args:
            address: 账户地址
            callback: 回调函数
            symbol: 交易对（可选）
        """
        channel = f"orders.{address}"
        if symbol:
            channel += f".{symbol}"
            
        params = {'address': address}
        if symbol:
            params['symbol'] = symbol
            
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅订单更新: {address} {symbol or 'all'}")
        
    async def subscribe_positions(
        self,
        address: str,
        callback: Callable
    ):
        """
        订阅持仓更新
        
        Args:
            address: 账户地址
            callback: 回调函数
        """
        channel = f"positions.{address}"
        params = {'address': address}
        
        # 添加订阅
        self.subscriptions[channel] = params
        if channel not in self.callbacks:
            self.callbacks[channel] = []
        self.callbacks[channel].append(callback)
        
        # 发送订阅
        await self._send_subscribe(channel, params)
        logger.info(f"订阅持仓更新: {address}")
        
    async def unsubscribe(self, channel: str):
        """
        取消订阅
        
        Args:
            channel: 频道名称
        """
        if channel in self.subscriptions:
            del self.subscriptions[channel]
        if channel in self.callbacks:
            del self.callbacks[channel]
            
        await self._send_unsubscribe(channel)
        logger.info(f"取消订阅: {channel}")
        
    async def unsubscribe_all(self):
        """取消所有订阅"""
        channels = list(self.subscriptions.keys())
        for channel in channels:
            await self.unsubscribe(channel)
            
        logger.info("已取消所有订阅")