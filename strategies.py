"""
交易策略模块
提供各种交易策略的实现
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
import numpy as np
from loguru import logger
from lighter_client import LighterClient
from risk_manager import RiskManager
from websocket_client import WebSocketClient


class BaseStrategy:
    """策略基类"""
    
    def __init__(
        self,
        client: LighterClient,
        risk_manager: RiskManager,
        ws_client: Optional[WebSocketClient] = None
    ):
        """
        初始化策略
        
        Args:
            client: Lighter客户端
            risk_manager: 风险管理器
            ws_client: WebSocket客户端
        """
        self.client = client
        self.risk_manager = risk_manager
        self.ws_client = ws_client
        
        # 策略参数
        self.symbol = None
        self.is_running = False
        self.position = {}
        self.orders = []
        
    async def start(self, symbol: str):
        """
        启动策略
        
        Args:
            symbol: 交易对
        """
        self.symbol = symbol
        self.is_running = True
        logger.info(f"启动策略: {self.__class__.__name__} - {symbol}")
        
        # 订阅WebSocket数据
        if self.ws_client:
            await self._setup_subscriptions()
            
        # 运行策略主循环
        await self.run()
        
    async def stop(self):
        """停止策略"""
        self.is_running = False
        
        # 取消所有订单
        await self.client.cancel_all_orders(self.symbol)
        
        # 平仓
        if self.position:
            await self._close_position()
            
        logger.info(f"停止策略: {self.__class__.__name__}")
        
    async def run(self):
        """策略主循环（子类实现）"""
        raise NotImplementedError
        
    async def _setup_subscriptions(self):
        """设置WebSocket订阅（子类可重写）"""
        pass
        
    async def _close_position(self):
        """平仓"""
        if not self.position or self.position.get('size', 0) == 0:
            return
            
        side = 'sell' if self.position['side'] == 'buy' else 'buy'
        quantity = abs(self.position['size'])
        
        try:
            order = await self.client.place_order(
                symbol=self.symbol,
                side=side,
                order_type='market',
                quantity=quantity,
                reduce_only=True
            )
            logger.info(f"平仓订单: {order}")
        except Exception as e:
            logger.error(f"平仓失败: {e}")


class GridTradingStrategy(BaseStrategy):
    """网格交易策略"""
    
    def __init__(
        self,
        client: LighterClient,
        risk_manager: RiskManager,
        ws_client: Optional[WebSocketClient] = None,
        grid_levels: int = 10,
        grid_spacing: float = 0.01,
        order_size: float = 100
    ):
        """
        初始化网格交易策略
        
        Args:
            client: Lighter客户端
            risk_manager: 风险管理器
            ws_client: WebSocket客户端
            grid_levels: 网格层数
            grid_spacing: 网格间距（百分比）
            order_size: 每格订单大小
        """
        super().__init__(client, risk_manager, ws_client)
        
        self.grid_levels = grid_levels
        self.grid_spacing = grid_spacing
        self.order_size = order_size
        
        self.grid_orders = {'buy': [], 'sell': []}
        self.base_price = None
        
    async def run(self):
        """运行网格交易策略"""
        try:
            # 获取当前价格
            orderbook = await self.client.get_orderbook(self.symbol, depth=1)
            self.base_price = (orderbook['best_bid'] + orderbook['best_ask']) / 2
            
            logger.info(f"网格交易基准价格: {self.base_price}")
            
            # 创建网格
            await self._create_grid()
            
            # 监控网格
            while self.is_running:
                await self._monitor_grid()
                await asyncio.sleep(10)  # 每10秒检查一次
                
        except Exception as e:
            logger.error(f"网格交易策略错误: {e}")
            await self.stop()
            
    async def _create_grid(self):
        """创建网格订单"""
        try:
            # 清除旧网格
            await self._clear_grid()
            
            # 创建买单网格
            for i in range(1, self.grid_levels + 1):
                price = self.base_price * (1 - self.grid_spacing * i)
                order = await self.client.place_order(
                    symbol=self.symbol,
                    side='buy',
                    order_type='limit',
                    quantity=self.order_size,
                    price=price
                )
                self.grid_orders['buy'].append(order)
                logger.debug(f"创建买单网格: {price}")
                
            # 创建卖单网格
            for i in range(1, self.grid_levels + 1):
                price = self.base_price * (1 + self.grid_spacing * i)
                order = await self.client.place_order(
                    symbol=self.symbol,
                    side='sell',
                    order_type='limit',
                    quantity=self.order_size,
                    price=price
                )
                self.grid_orders['sell'].append(order)
                logger.debug(f"创建卖单网格: {price}")
                
            logger.info(f"网格创建完成: {len(self.grid_orders['buy'])}买单, {len(self.grid_orders['sell'])}卖单")
            
        except Exception as e:
            logger.error(f"创建网格失败: {e}")
            raise
            
    async def _monitor_grid(self):
        """监控网格状态"""
        try:
            # 获取未完成订单
            open_orders = await self.client.get_open_orders(self.symbol)
            open_order_ids = {order['id'] for order in open_orders}
            
            # 检查成交的订单
            for side in ['buy', 'sell']:
                for order in self.grid_orders[side]:
                    if order.get('orderId') not in open_order_ids:
                        # 订单已成交，创建新的网格订单
                        await self._replace_grid_order(side, order)
                        
        except Exception as e:
            logger.error(f"监控网格失败: {e}")
            
    async def _replace_grid_order(self, side: str, filled_order: Dict):
        """
        替换成交的网格订单
        
        Args:
            side: 订单方向
            filled_order: 已成交的订单
        """
        try:
            # 计算新订单的价格
            if side == 'buy':
                # 买单成交后，在更高价格创建卖单
                new_price = float(filled_order.get('price', 0)) * (1 + self.grid_spacing * 2)
                new_side = 'sell'
            else:
                # 卖单成交后，在更低价格创建买单
                new_price = float(filled_order.get('price', 0)) * (1 - self.grid_spacing * 2)
                new_side = 'buy'
                
            # 创建新订单
            new_order = await self.client.place_order(
                symbol=self.symbol,
                side=new_side,
                order_type='limit',
                quantity=self.order_size,
                price=new_price
            )
            
            # 更新网格订单列表
            self.grid_orders[side].remove(filled_order)
            self.grid_orders[new_side].append(new_order)
            
            logger.info(f"网格订单替换: {filled_order.get('orderId')} -> {new_order.get('orderId')}")
            
        except Exception as e:
            logger.error(f"替换网格订单失败: {e}")
            
    async def _clear_grid(self):
        """清除网格订单"""
        try:
            # 取消所有网格订单
            for side in ['buy', 'sell']:
                for order in self.grid_orders[side]:
                    try:
                        await self.client.cancel_order(order_id=order.get('orderId'))
                    except Exception as e:
                        logger.warning(f"取消网格订单失败: {e}")
                        
            self.grid_orders = {'buy': [], 'sell': []}
            logger.info("网格订单已清除")
            
        except Exception as e:
            logger.error(f"清除网格失败: {e}")


class MomentumStrategy(BaseStrategy):
    """动量交易策略"""
    
    def __init__(
        self,
        client: LighterClient,
        risk_manager: RiskManager,
        ws_client: Optional[WebSocketClient] = None,
        lookback_period: int = 20,
        momentum_threshold: float = 0.02,
        position_size: float = 1000
    ):
        """
        初始化动量策略
        
        Args:
            client: Lighter客户端
            risk_manager: 风险管理器
            ws_client: WebSocket客户端
            lookback_period: 回望期
            momentum_threshold: 动量阈值
            position_size: 仓位大小
        """
        super().__init__(client, risk_manager, ws_client)
        
        self.lookback_period = lookback_period
        self.momentum_threshold = momentum_threshold
        self.position_size = position_size
        
        self.price_history = []
        
    async def run(self):
        """运行动量策略"""
        try:
            while self.is_running:
                # 获取K线数据
                candles = await self.client.get_candlesticks(
                    symbol=self.symbol,
                    interval='5m',
                    limit=self.lookback_period + 1
                )
                
                if len(candles) >= self.lookback_period:
                    # 计算动量
                    momentum = self._calculate_momentum(candles)
                    
                    # 生成交易信号
                    signal = self._generate_signal(momentum)
                    
                    # 执行交易
                    if signal != 0:
                        await self._execute_trade(signal)
                        
                # 等待下一个周期
                await asyncio.sleep(300)  # 5分钟
                
        except Exception as e:
            logger.error(f"动量策略错误: {e}")
            await self.stop()
            
    def _calculate_momentum(self, candles: pd.DataFrame) -> float:
        """
        计算动量
        
        Args:
            candles: K线数据
            
        Returns:
            动量值
        """
        try:
            # 计算收益率
            returns = candles['close'].pct_change()
            
            # 计算累积收益率作为动量
            momentum = (1 + returns).prod() - 1
            
            return float(momentum)
            
        except Exception as e:
            logger.error(f"计算动量失败: {e}")
            return 0
            
    def _generate_signal(self, momentum: float) -> int:
        """
        生成交易信号
        
        Args:
            momentum: 动量值
            
        Returns:
            信号 (1=买入, -1=卖出, 0=无信号)
        """
        if momentum > self.momentum_threshold:
            return 1  # 买入信号
        elif momentum < -self.momentum_threshold:
            return -1  # 卖出信号
        else:
            return 0  # 无信号
            
    async def _execute_trade(self, signal: int):
        """
        执行交易
        
        Args:
            signal: 交易信号
        """
        try:
            # 获取当前持仓
            positions = await self.client.get_account_positions()
            current_position = 0
            for pos in positions:
                if pos['symbol'] == self.symbol:
                    current_position = pos['size'] if pos['side'] == 'buy' else -pos['size']
                    
            # 计算目标仓位
            target_position = signal * self.position_size
            
            # 计算需要交易的数量
            trade_quantity = abs(target_position - current_position)
            
            if trade_quantity > 0:
                # 确定交易方向
                if target_position > current_position:
                    side = 'buy'
                else:
                    side = 'sell'
                    
                # 风险检查
                passed, reason = await self.risk_manager.check_position_limits(
                    self.symbol, side, trade_quantity
                )
                
                if passed:
                    # 下单
                    order = await self.client.place_order(
                        symbol=self.symbol,
                        side=side,
                        order_type='market',
                        quantity=trade_quantity
                    )
                    
                    # 设置止损止盈
                    orderbook = await self.client.get_orderbook(self.symbol, depth=1)
                    entry_price = orderbook['best_ask'] if side == 'buy' else orderbook['best_bid']
                    
                    await self.risk_manager.set_stop_loss_take_profit(
                        symbol=self.symbol,
                        side=side,
                        entry_price=entry_price,
                        quantity=trade_quantity
                    )
                    
                    logger.info(f"动量交易执行: {side} {trade_quantity} @ market")
                else:
                    logger.warning(f"风险检查未通过: {reason}")
                    
        except Exception as e:
            logger.error(f"执行交易失败: {e}")


class ArbitrageStrategy(BaseStrategy):
    """套利策略"""
    
    def __init__(
        self,
        client: LighterClient,
        risk_manager: RiskManager,
        ws_client: Optional[WebSocketClient] = None,
        spread_threshold: float = 0.002,
        trade_size: float = 1000
    ):
        """
        初始化套利策略
        
        Args:
            client: Lighter客户端
            risk_manager: 风险管理器
            ws_client: WebSocket客户端
            spread_threshold: 价差阈值
            trade_size: 交易大小
        """
        super().__init__(client, risk_manager, ws_client)
        
        self.spread_threshold = spread_threshold
        self.trade_size = trade_size
        self.orderbook_data = {}
        
    async def _setup_subscriptions(self):
        """设置WebSocket订阅"""
        if self.ws_client:
            await self.ws_client.subscribe_orderbook(
                self.symbol,
                self._on_orderbook_update,
                depth=5
            )
            
    async def _on_orderbook_update(self, data: Dict):
        """
        订单簿更新回调
        
        Args:
            data: 订单簿数据
        """
        try:
            symbol = data.get('symbol')
            self.orderbook_data[symbol] = {
                'bids': data.get('bids', []),
                'asks': data.get('asks', []),
                'timestamp': datetime.now()
            }
            
            # 检查套利机会
            await self._check_arbitrage()
            
        except Exception as e:
            logger.error(f"处理订单簿更新失败: {e}")
            
    async def _check_arbitrage(self):
        """检查套利机会"""
        try:
            if self.symbol not in self.orderbook_data:
                return
                
            orderbook = self.orderbook_data[self.symbol]
            
            if not orderbook['bids'] or not orderbook['asks']:
                return
                
            # 计算价差
            best_bid = float(orderbook['bids'][0][0])
            best_ask = float(orderbook['asks'][0][0])
            spread = (best_ask - best_bid) / best_bid
            
            # 检查是否存在套利机会
            if spread > self.spread_threshold:
                await self._execute_arbitrage(best_bid, best_ask)
                
        except Exception as e:
            logger.error(f"检查套利失败: {e}")
            
    async def _execute_arbitrage(self, bid_price: float, ask_price: float):
        """
        执行套利交易
        
        Args:
            bid_price: 买价
            ask_price: 卖价
        """
        try:
            # 这里实现具体的套利逻辑
            # 例如：跨市场套利、三角套利等
            
            logger.info(f"发现套利机会: 买价={bid_price}, 卖价={ask_price}")
            
            # 示例：简单的做市策略
            # 在买价上方下买单，在卖价下方下卖单
            buy_price = bid_price * 1.0001
            sell_price = ask_price * 0.9999
            
            # 同时下买卖单
            orders = await self.client.place_batch_orders([
                {
                    'symbol': self.symbol,
                    'side': 'buy',
                    'quantity': self.trade_size,
                    'price': buy_price
                },
                {
                    'symbol': self.symbol,
                    'side': 'sell',
                    'quantity': self.trade_size,
                    'price': sell_price
                }
            ])
            
            logger.info(f"套利订单已下: {len(orders)} 个")
            
        except Exception as e:
            logger.error(f"执行套利失败: {e}")
            
    async def run(self):
        """运行套利策略"""
        try:
            # 如果没有WebSocket，使用轮询
            if not self.ws_client:
                while self.is_running:
                    orderbook = await self.client.get_orderbook(self.symbol, depth=5)
                    self.orderbook_data[self.symbol] = {
                        'bids': orderbook['bids'],
                        'asks': orderbook['asks'],
                        'timestamp': datetime.now()
                    }
                    
                    await self._check_arbitrage()
                    await asyncio.sleep(1)  # 每秒检查一次
            else:
                # 使用WebSocket，等待策略运行
                while self.is_running:
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.error(f"套利策略错误: {e}")
            await self.stop()