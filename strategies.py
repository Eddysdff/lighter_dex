"""
交易策略实现
包含自成交、网格交易、做市等策略
"""
import asyncio
import random
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
from loguru import logger
from lighter_client import LighterClient, Order, OrderSide, OrderType
from config import config, TradingStrategy

@dataclass
class StrategyStats:
    """策略统计数据"""
    executed_trades: int = 0
    total_volume: float = 0.0
    total_fees: float = 0.0
    realized_pnl: float = 0.0
    success_rate: float = 0.0
    start_time: float = 0.0
    
    def update(self, volume: float, fee: float, pnl: float = 0):
        """更新统计"""
        self.executed_trades += 1
        self.total_volume += volume
        self.total_fees += fee
        self.realized_pnl += pnl
        
    def get_summary(self) -> Dict:
        """获取统计摘要"""
        runtime = time.time() - self.start_time if self.start_time else 0
        hours = runtime / 3600
        
        return {
            "executed_trades": self.executed_trades,
            "total_volume": f"{self.total_volume:,.2f} USDT",
            "total_fees": f"{self.total_fees:.4f} USDT",
            "realized_pnl": f"{self.realized_pnl:.4f} USDT",
            "net_result": f"{self.realized_pnl - self.total_fees:.4f} USDT",
            "volume_per_hour": f"{self.total_volume/hours:,.2f} USDT/h" if hours > 0 else "N/A",
            "trades_per_hour": f"{self.executed_trades/hours:.1f}" if hours > 0 else "N/A"
        }

class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, client: LighterClient, symbol: str = None):
        self.client = client
        self.symbol = symbol or config.symbol
        self.stats = StrategyStats(start_time=time.time())
        self.running = False
        self.open_orders: List[Order] = []
        
    @abstractmethod
    async def execute(self):
        """执行策略（子类实现）"""
        pass
        
    async def start(self):
        """启动策略"""
        self.running = True
        logger.info(f"🚀 启动策略: {self.__class__.__name__}")
        
        try:
            while self.running:
                await self.execute()
                await asyncio.sleep(config.order_interval_seconds)
        except KeyboardInterrupt:
            logger.info("⚠️ 收到中断信号")
        except Exception as e:
            logger.error(f"❌ 策略执行错误: {e}")
        finally:
            await self.cleanup()
            
    async def stop(self):
        """停止策略"""
        self.running = False
        logger.info(f"🛑 停止策略: {self.__class__.__name__}")
        
    async def cleanup(self):
        """清理资源"""
        logger.info("🧹 清理未完成订单...")
        cancelled = await self.client.cancel_all_orders(self.symbol)
        logger.info(f"✅ 已取消 {cancelled} 个订单")
        
        # 打印统计
        stats = self.stats.get_summary()
        logger.info("📊 策略运行统计:")
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
            
    def calculate_order_size(self) -> float:
        """计算订单量（带随机性）"""
        base_size = random.uniform(config.min_order_size, config.max_order_size)
        variance = base_size * config.order_size_variance
        return round(base_size + random.uniform(-variance, variance), 2)
        
    def calculate_price_offset(self, mid_price: float, is_buy: bool) -> float:
        """计算价格偏移"""
        offset_ratio = config.price_offset_bps / 10000
        offset = mid_price * offset_ratio
        
        if is_buy:
            return round(mid_price - offset, 2)
        else:
            return round(mid_price + offset, 2)

class SelfTradeStrategy(BaseStrategy):
    """
    自成交策略（对敲）
    通过快速买卖制造交易量，成本最低但风险较高
    """
    
    async def execute(self):
        """执行自成交"""
        try:
            # 获取当前价格
            ticker = await self.client.get_ticker(self.symbol)
            mid_price = (ticker['bid'] + ticker['ask']) / 2
            
            # 计算订单参数
            order_size = self.calculate_order_size()
            spread = mid_price * (config.spread_bps / 10000)
            
            # 方案1: 同时下买卖单，价格交叉实现成交
            buy_price = round(mid_price + spread/2, 2)
            sell_price = round(mid_price - spread/2, 2)
            
            # 确保价格交叉（买价高于卖价）
            if buy_price > sell_price:
                logger.info(f"🔄 自成交 - 价格: {mid_price:.2f}, 量: {order_size:.2f} USDT")
                
                # 同时下买卖单
                tasks = [
                    self.client.create_order(
                        symbol=self.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        amount=order_size / mid_price,  # 转换为币量
                        price=buy_price
                    ),
                    self.client.create_order(
                        symbol=self.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        amount=order_size / mid_price,
                        price=sell_price
                    )
                ]
                
                orders = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 处理结果
                for order in orders:
                    if isinstance(order, Order):
                        self.open_orders.append(order)
                        volume = order.amount * order.price
                        fee = volume * 0.001  # 假设0.1%手续费
                        self.stats.update(volume, fee)
                    else:
                        logger.error(f"订单失败: {order}")
                        
                # 等待成交或取消
                await asyncio.sleep(2)
                
                # 取消未成交订单
                for order in self.open_orders:
                    if order.status not in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
                        await self.client.cancel_order(order.id, self.symbol)
                        
                self.open_orders.clear()
                
            # 方案2: 使用市价单快速成交（成本较高）
            elif random.random() < 0.3:  # 30%概率使用市价单
                logger.info(f"💨 市价成交 - 量: {order_size:.2f} USDT")
                
                # 先买后卖
                buy_order = await self.client.create_order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    amount=order_size / mid_price
                )
                
                await asyncio.sleep(0.5)
                
                sell_order = await self.client.create_order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    amount=order_size / mid_price
                )
                
                # 更新统计
                for order in [buy_order, sell_order]:
                    volume = order.amount * mid_price
                    fee = volume * 0.001
                    self.stats.update(volume, fee)
                    
        except Exception as e:
            logger.error(f"自成交执行失败: {e}")

class GridStrategy(BaseStrategy):
    """
    网格交易策略
    在价格上下布置多个订单，等待市场波动成交
    """
    
    def __init__(self, client: LighterClient, symbol: str = None):
        super().__init__(client, symbol)
        self.grid_orders: Dict[str, Dict] = {}  # 网格订单追踪
        
    async def execute(self):
        """执行网格策略"""
        try:
            # 获取当前价格和订单簿
            ticker = await self.client.get_ticker(self.symbol)
            orderbook = await self.client.get_orderbook(self.symbol, depth=5)
            
            mid_price = (ticker['bid'] + ticker['ask']) / 2
            
            # 清理已成交或取消的订单
            await self._clean_filled_orders()
            
            # 如果网格订单不足，补充订单
            if len(self.grid_orders) < config.grid_levels * 2:
                await self._place_grid_orders(mid_price, orderbook)
                
            # 检查是否需要调整网格
            if await self._should_adjust_grid(mid_price):
                await self._adjust_grid(mid_price)
                
            # 更新统计
            await self._update_grid_stats()
            
        except Exception as e:
            logger.error(f"网格策略执行失败: {e}")
            
    async def _place_grid_orders(self, mid_price: float, orderbook: Dict):
        """放置网格订单"""
        grid_spacing = mid_price * (config.grid_spacing_bps / 10000)
        order_size = config.grid_order_size
        
        orders_to_place = []
        
        # 计算买单价格（低于当前价）
        for i in range(1, config.grid_levels + 1):
            buy_price = round(mid_price - grid_spacing * i, 2)
            
            # 检查是否已有订单在该价格
            if not self._has_order_at_price(buy_price, OrderSide.BUY):
                orders_to_place.append({
                    "symbol": self.symbol,
                    "side": OrderSide.BUY,
                    "order_type": OrderType.LIMIT_MAKER,  # 只做Maker
                    "amount": order_size / buy_price,
                    "price": buy_price
                })
                
        # 计算卖单价格（高于当前价）
        for i in range(1, config.grid_levels + 1):
            sell_price = round(mid_price + grid_spacing * i, 2)
            
            if not self._has_order_at_price(sell_price, OrderSide.SELL):
                orders_to_place.append({
                    "symbol": self.symbol,
                    "side": OrderSide.SELL,
                    "order_type": OrderType.LIMIT_MAKER,
                    "amount": order_size / sell_price,
                    "price": sell_price
                })
                
        # 批量下单
        if orders_to_place:
            logger.info(f"📊 放置 {len(orders_to_place)} 个网格订单")
            orders = await self.client.create_batch_orders(orders_to_place)
            
            # 记录订单
            for order in orders:
                if order:
                    self.grid_orders[order.id] = {
                        "order": order,
                        "placed_at": time.time(),
                        "price": order.price,
                        "side": order.side
                    }
                    
    async def _clean_filled_orders(self):
        """清理已成交订单"""
        to_remove = []
        
        for order_id, grid_order in self.grid_orders.items():
            order = await self.client.get_order(order_id)
            
            if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
                to_remove.append(order_id)
                
                if order.status == OrderStatus.FILLED:
                    # 统计成交
                    volume = order.amount * order.price
                    fee = order.fee or (volume * 0.001)
                    self.stats.update(volume, fee)
                    
                    # 在对面放置新订单（实现网格循环）
                    await self._place_counter_order(order)
                    
        # 移除已处理订单
        for order_id in to_remove:
            del self.grid_orders[order_id]
            
    async def _place_counter_order(self, filled_order: Order):
        """成交后在对面放置新订单"""
        grid_spacing = filled_order.price * (config.grid_spacing_bps * 2 / 10000)
        
        if filled_order.side == OrderSide.BUY:
            # 买单成交，在上方放置卖单
            counter_price = round(filled_order.price + grid_spacing, 2)
            counter_side = OrderSide.SELL
        else:
            # 卖单成交，在下方放置买单
            counter_price = round(filled_order.price - grid_spacing, 2)
            counter_side = OrderSide.BUY
            
        counter_order = await self.client.create_order(
            symbol=self.symbol,
            side=counter_side,
            order_type=OrderType.LIMIT_MAKER,
            amount=filled_order.amount,
            price=counter_price
        )
        
        if counter_order:
            self.grid_orders[counter_order.id] = {
                "order": counter_order,
                "placed_at": time.time(),
                "price": counter_price,
                "side": counter_side
            }
            
    async def _should_adjust_grid(self, current_price: float) -> bool:
        """判断是否需要调整网格"""
        if not self.grid_orders:
            return False
            
        prices = [go["price"] for go in self.grid_orders.values()]
        min_price = min(prices)
        max_price = max(prices)
        
        # 如果价格超出网格范围，需要调整
        return current_price < min_price * 1.1 or current_price > max_price * 0.9
        
    async def _adjust_grid(self, current_price: float):
        """调整网格位置"""
        logger.info(f"🔧 调整网格中心到: {current_price:.2f}")
        
        # 取消所有现有订单
        for order_id in list(self.grid_orders.keys()):
            await self.client.cancel_order(order_id, self.symbol)
            
        self.grid_orders.clear()
        
        # 重新放置网格
        orderbook = await self.client.get_orderbook(self.symbol, depth=5)
        await self._place_grid_orders(current_price, orderbook)
        
    def _has_order_at_price(self, price: float, side: OrderSide) -> bool:
        """检查是否已有订单在指定价格"""
        for grid_order in self.grid_orders.values():
            if abs(grid_order["price"] - price) < 0.01 and grid_order["side"] == side:
                return True
        return False
        
    async def _update_grid_stats(self):
        """更新网格统计"""
        active_orders = len(self.grid_orders)
        if active_orders > 0 and self.stats.executed_trades % 10 == 0:
            logger.info(f"📈 网格状态 - 活跃订单: {active_orders}, 成交: {self.stats.executed_trades}, 交易量: {self.stats.total_volume:.2f} USDT")

class MarketMakerStrategy(BaseStrategy):
    """
    做市商策略
    同时提供买卖流动性，赚取价差
    """
    
    async def execute(self):
        """执行做市策略"""
        try:
            # 获取市场数据
            ticker = await self.client.get_ticker(self.symbol)
            orderbook = await self.client.get_orderbook(self.symbol, depth=10)
            
            # 计算公平价格
            fair_price = self._calculate_fair_price(ticker, orderbook)
            
            # 取消旧订单
            await self._cancel_stale_orders()
            
            # 计算报价
            bid_price, ask_price = self._calculate_quotes(fair_price, orderbook)
            
            # 计算订单量（基于库存平衡）
            bid_size, ask_size = await self._calculate_sizes()
            
            # 下单
            if bid_price and bid_size > 0:
                await self.client.create_order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    amount=bid_size,
                    price=bid_price
                )
                
            if ask_price and ask_size > 0:
                await self.client.create_order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT_MAKER,
                    amount=ask_size,
                    price=ask_price
                )
                
            # 更新统计
            await self._update_maker_stats()
            
        except Exception as e:
            logger.error(f"做市策略执行失败: {e}")
            
    def _calculate_fair_price(self, ticker: Dict, orderbook: Dict) -> float:
        """计算公平价格"""
        # 简单实现：使用加权平均
        bid_price = orderbook['bids'][0][0] if orderbook['bids'] else ticker['bid']
        ask_price = orderbook['asks'][0][0] if orderbook['asks'] else ticker['ask']
        
        bid_volume = sum(q for p, q in orderbook['bids'][:5])
        ask_volume = sum(q for p, q in orderbook['asks'][:5])
        
        if bid_volume + ask_volume > 0:
            fair_price = (bid_price * bid_volume + ask_price * ask_volume) / (bid_volume + ask_volume)
        else:
            fair_price = (bid_price + ask_price) / 2
            
        return round(fair_price, 2)
        
    def _calculate_quotes(self, fair_price: float, orderbook: Dict) -> Tuple[float, float]:
        """计算报价"""
        spread = fair_price * (config.spread_bps / 10000)
        
        # 基础报价
        bid_price = fair_price - spread / 2
        ask_price = fair_price + spread / 2
        
        # 确保不会被立即成交（避免与最优价格交叉）
        if orderbook['asks']:
            best_ask = orderbook['asks'][0][0]
            bid_price = min(bid_price, best_ask - 0.01)
            
        if orderbook['bids']:
            best_bid = orderbook['bids'][0][0]
            ask_price = max(ask_price, best_bid + 0.01)
            
        return round(bid_price, 2), round(ask_price, 2)
        
    async def _calculate_sizes(self) -> Tuple[float, float]:
        """计算订单量（考虑库存平衡）"""
        base_size = self.calculate_order_size()
        
        # 获取当前持仓
        positions = await self.client.get_positions()
        position = next((p for p in positions if p.symbol == self.symbol), None)
        
        if position:
            # 根据持仓调整订单量
            if position.amount > 0:  # 多头持仓
                # 增加卖单量，减少买单量
                bid_size = base_size * 0.7
                ask_size = base_size * 1.3
            elif position.amount < 0:  # 空头持仓
                # 增加买单量，减少卖单量
                bid_size = base_size * 1.3
                ask_size = base_size * 0.7
            else:
                bid_size = ask_size = base_size
        else:
            bid_size = ask_size = base_size
            
        return bid_size, ask_size
        
    async def _cancel_stale_orders(self):
        """取消过期订单"""
        open_orders = await self.client.get_open_orders(self.symbol)
        current_time = time.time()
        
        for order in open_orders:
            # 超过指定时间未成交则取消
            if current_time - order.timestamp > config.cancel_after_seconds:
                await self.client.cancel_order(order.id, self.symbol)
                
    async def _update_maker_stats(self):
        """更新做市统计"""
        if self.stats.executed_trades % 20 == 0:
            stats = self.stats.get_summary()
            logger.info(f"🏪 做市统计 - {stats['executed_trades']} 笔, 量: {stats['total_volume']}, 净: {stats['net_result']}")

class HybridStrategy(BaseStrategy):
    """
    混合策略
    结合多种策略，根据市场情况动态切换
    """
    
    def __init__(self, client: LighterClient, symbol: str = None):
        super().__init__(client, symbol)
        self.strategies = {
            TradingStrategy.SELF_TRADE: SelfTradeStrategy(client, symbol),
            TradingStrategy.GRID: GridStrategy(client, symbol),
            TradingStrategy.MARKET_MAKE: MarketMakerStrategy(client, symbol)
        }
        self.current_strategy = None
        self.strategy_rotation_time = 300  # 5分钟轮换
        self.last_rotation = time.time()
        
    async def execute(self):
        """执行混合策略"""
        try:
            # 检查是否需要切换策略
            if await self._should_rotate_strategy():
                await self._rotate_strategy()
                
            # 执行当前策略
            if self.current_strategy:
                await self.current_strategy.execute()
                
                # 合并统计
                self.stats.executed_trades = self.current_strategy.stats.executed_trades
                self.stats.total_volume = self.current_strategy.stats.total_volume
                self.stats.total_fees = self.current_strategy.stats.total_fees
                
        except Exception as e:
            logger.error(f"混合策略执行失败: {e}")
            
    async def _should_rotate_strategy(self) -> bool:
        """判断是否需要切换策略"""
        current_time = time.time()
        
        # 定时轮换
        if current_time - self.last_rotation > self.strategy_rotation_time:
            return True
            
        # 根据市场波动性切换
        ticker = await self.client.get_ticker(self.symbol)
        recent_trades = await self.client.get_recent_trades(self.symbol, limit=100)
        
        if recent_trades:
            prices = [t['price'] for t in recent_trades]
            volatility = (max(prices) - min(prices)) / ticker['last'] * 100
            
            # 高波动性适合网格
            if volatility > 1.0 and self.current_strategy != self.strategies[TradingStrategy.GRID]:
                logger.info(f"📊 检测到高波动性 ({volatility:.2f}%), 切换到网格策略")
                return True
                
            # 低波动性适合做市
            elif volatility < 0.3 and self.current_strategy != self.strategies[TradingStrategy.MARKET_MAKE]:
                logger.info(f"📊 检测到低波动性 ({volatility:.2f}%), 切换到做市策略")
                return True
                
        return False
        
    async def _rotate_strategy(self):
        """轮换策略"""
        # 停止当前策略
        if self.current_strategy:
            await self.current_strategy.cleanup()
            
        # 选择下一个策略
        strategies = list(self.strategies.values())
        weights = [0.3, 0.5, 0.2]  # 自成交30%, 网格50%, 做市20%
        
        self.current_strategy = random.choices(strategies, weights=weights)[0]
        self.last_rotation = time.time()
        
        logger.info(f"🔄 切换策略到: {self.current_strategy.__class__.__name__}")

# 策略工厂
def create_strategy(strategy_type: TradingStrategy, client: LighterClient, symbol: str = None) -> BaseStrategy:
    """创建策略实例"""
    strategies = {
        TradingStrategy.SELF_TRADE: SelfTradeStrategy,
        TradingStrategy.GRID: GridStrategy,
        TradingStrategy.MARKET_MAKE: MarketMakerStrategy,
        TradingStrategy.HYBRID: HybridStrategy
    }
    
    strategy_class = strategies.get(strategy_type)
    if not strategy_class:
        raise ValueError(f"未知策略类型: {strategy_type}")
        
    return strategy_class(client, symbol)

# 测试代码
async def test_strategies():
    """测试策略"""
    from lighter_client import LighterClient
    
    async with LighterClient() as client:
        # 测试自成交策略
        strategy = SelfTradeStrategy(client)
        
        # 运行10秒
        task = asyncio.create_task(strategy.start())
        await asyncio.sleep(10)
        await strategy.stop()
        
        try:
            await task
        except:
            pass

if __name__ == "__main__":
    asyncio.run(test_strategies())