"""
风险管理模块
提供仓位管理、止损止盈、资金管理等功能
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
from loguru import logger
from config import get_config
from lighter_client import LighterClient


class RiskManager:
    """风险管理器"""
    
    def __init__(self, client: LighterClient, config=None):
        """
        初始化风险管理器
        
        Args:
            client: Lighter客户端
            config: 配置对象
        """
        self.client = client
        self.config = config or get_config()
        
        # 风险参数
        self.max_position_size = self.config.max_position_size
        self.max_drawdown = self.config.max_drawdown
        self.stop_loss_pct = self.config.stop_loss_percentage
        self.take_profit_pct = self.config.take_profit_percentage
        
        # 状态追踪
        self.positions = {}
        self.peak_balance = 0
        self.current_drawdown = 0
        self.risk_alerts = []
        
    async def check_position_limits(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int = 1
    ) -> Tuple[bool, str]:
        """
        检查仓位限制
        
        Args:
            symbol: 交易对
            side: 方向
            quantity: 数量
            leverage: 杠杆
            
        Returns:
            (是否通过, 原因)
        """
        try:
            # 获取当前持仓
            positions = await self.client.get_account_positions()
            
            # 计算当前仓位大小
            current_position = 0
            for pos in positions:
                if pos['symbol'] == symbol:
                    current_position += abs(pos['size'])
                    
            # 计算新仓位大小
            new_position = current_position + quantity * leverage
            
            # 检查是否超过限制
            if new_position > self.max_position_size:
                msg = f"仓位超过限制: {new_position} > {self.max_position_size}"
                logger.warning(msg)
                return False, msg
                
            # 检查账户余额
            balance = await self.client.get_account_balance()
            required_margin = quantity * leverage / 10  # 假设10倍最大杠杆
            
            if balance['available_balance'] < required_margin:
                msg = f"余额不足: {balance['available_balance']} < {required_margin}"
                logger.warning(msg)
                return False, msg
                
            return True, "通过风险检查"
            
        except Exception as e:
            logger.error(f"检查仓位限制失败: {e}")
            return False, str(e)
            
    async def calculate_position_size(
        self,
        symbol: str,
        risk_amount: float,
        stop_loss_price: float,
        entry_price: float
    ) -> float:
        """
        根据风险金额计算仓位大小
        
        Args:
            symbol: 交易对
            risk_amount: 风险金额
            stop_loss_price: 止损价格
            entry_price: 入场价格
            
        Returns:
            建议的仓位大小
        """
        try:
            # 计算止损距离
            stop_loss_distance = abs(entry_price - stop_loss_price)
            
            # 计算仓位大小
            position_size = risk_amount / stop_loss_distance
            
            # 应用精度限制
            from config import MarketConfig
            precision = MarketConfig.PRECISION.get(symbol, {}).get('quantity', 4)
            position_size = round(position_size, precision)
            
            # 检查最大仓位限制
            position_size = min(position_size, self.max_position_size)
            
            logger.info(f"计算仓位大小: {position_size} (风险: {risk_amount}, 止损: {stop_loss_distance})")
            return position_size
            
        except Exception as e:
            logger.error(f"计算仓位大小失败: {e}")
            raise
            
    async def set_stop_loss_take_profit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None
    ) -> Dict:
        """
        设置止损止盈订单
        
        Args:
            symbol: 交易对
            side: 持仓方向
            entry_price: 入场价格
            quantity: 数量
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            
        Returns:
            止损止盈订单信息
        """
        try:
            orders = {}
            
            # 使用默认值
            if stop_loss_pct is None:
                stop_loss_pct = self.stop_loss_pct
            if take_profit_pct is None:
                take_profit_pct = self.take_profit_pct
                
            # 计算止损止盈价格
            if side == 'buy':
                stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
                take_profit_price = entry_price * (1 + take_profit_pct / 100)
                sl_side = 'sell'
            else:
                stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
                take_profit_price = entry_price * (1 - take_profit_pct / 100)
                sl_side = 'buy'
                
            # 下止损单
            if stop_loss_pct > 0:
                sl_order = await self.client.place_order(
                    symbol=symbol,
                    side=sl_side,
                    order_type='stop',
                    quantity=quantity,
                    stop_price=stop_loss_price,
                    reduce_only=True
                )
                orders['stop_loss'] = sl_order
                logger.info(f"设置止损: {stop_loss_price}")
                
            # 下止盈单
            if take_profit_pct > 0:
                tp_order = await self.client.place_order(
                    symbol=symbol,
                    side=sl_side,
                    order_type='limit',
                    quantity=quantity,
                    price=take_profit_price,
                    reduce_only=True
                )
                orders['take_profit'] = tp_order
                logger.info(f"设置止盈: {take_profit_price}")
                
            return orders
            
        except Exception as e:
            logger.error(f"设置止损止盈失败: {e}")
            raise
            
    async def monitor_drawdown(self) -> Dict:
        """
        监控回撤
        
        Returns:
            回撤信息
        """
        try:
            # 获取当前余额
            balance = await self.client.get_account_balance()
            current_balance = balance['total_balance']
            
            # 更新峰值
            if current_balance > self.peak_balance:
                self.peak_balance = current_balance
                
            # 计算回撤
            if self.peak_balance > 0:
                self.current_drawdown = (self.peak_balance - current_balance) / self.peak_balance * 100
            else:
                self.current_drawdown = 0
                
            # 检查是否超过最大回撤
            if self.current_drawdown > self.max_drawdown:
                alert = {
                    'type': 'MAX_DRAWDOWN_EXCEEDED',
                    'timestamp': datetime.now(),
                    'drawdown': self.current_drawdown,
                    'limit': self.max_drawdown,
                    'action': 'STOP_TRADING'
                }
                self.risk_alerts.append(alert)
                logger.error(f"超过最大回撤限制: {self.current_drawdown:.2f}% > {self.max_drawdown}%")
                
                # 取消所有订单
                await self.client.cancel_all_orders()
                
            return {
                'current_balance': current_balance,
                'peak_balance': self.peak_balance,
                'drawdown': self.current_drawdown,
                'max_drawdown': self.max_drawdown,
                'is_exceeded': self.current_drawdown > self.max_drawdown
            }
            
        except Exception as e:
            logger.error(f"监控回撤失败: {e}")
            raise
            
    async def rebalance_portfolio(
        self,
        target_allocations: Dict[str, float]
    ) -> List[Dict]:
        """
        重新平衡投资组合
        
        Args:
            target_allocations: 目标配置 {symbol: percentage}
            
        Returns:
            重新平衡订单列表
        """
        try:
            # 获取当前持仓和余额
            positions = await self.client.get_account_positions()
            balance = await self.client.get_account_balance()
            total_value = balance['total_balance']
            
            # 计算当前配置
            current_allocations = {}
            for pos in positions:
                symbol = pos['symbol']
                position_value = pos['size'] * pos['mark_price']
                current_allocations[symbol] = position_value / total_value * 100
                
            # 计算需要的调整
            adjustments = []
            for symbol, target_pct in target_allocations.items():
                current_pct = current_allocations.get(symbol, 0)
                diff_pct = target_pct - current_pct
                
                if abs(diff_pct) > 1:  # 只有差异大于1%才调整
                    # 计算需要买卖的数量
                    target_value = total_value * target_pct / 100
                    current_value = total_value * current_pct / 100
                    diff_value = target_value - current_value
                    
                    # 获取当前价格
                    orderbook = await self.client.get_orderbook(symbol, depth=1)
                    price = orderbook['best_ask'] if diff_value > 0 else orderbook['best_bid']
                    
                    quantity = abs(diff_value / price)
                    side = 'buy' if diff_value > 0 else 'sell'
                    
                    adjustments.append({
                        'symbol': symbol,
                        'side': side,
                        'quantity': quantity,
                        'price': price,
                        'current_pct': current_pct,
                        'target_pct': target_pct
                    })
                    
            # 执行调整订单
            orders = []
            for adj in adjustments:
                try:
                    order = await self.client.place_order(
                        symbol=adj['symbol'],
                        side=adj['side'],
                        order_type='limit',
                        quantity=adj['quantity'],
                        price=adj['price']
                    )
                    orders.append(order)
                    logger.info(f"重新平衡: {adj['symbol']} {adj['current_pct']:.1f}% -> {adj['target_pct']:.1f}%")
                except Exception as e:
                    logger.error(f"重新平衡订单失败: {e}")
                    
            return orders
            
        except Exception as e:
            logger.error(f"重新平衡投资组合失败: {e}")
            raise
            
    async def get_risk_metrics(self) -> Dict:
        """
        获取风险指标
        
        Returns:
            风险指标字典
        """
        try:
            # 获取账户信息
            balance = await self.client.get_account_balance()
            positions = await self.client.get_account_positions()
            
            # 计算总暴露
            total_exposure = sum(abs(pos['size'] * pos['mark_price']) for pos in positions)
            
            # 计算杠杆
            leverage = total_exposure / balance['total_balance'] if balance['total_balance'] > 0 else 0
            
            # 计算风险值
            position_count = len(positions)
            unrealized_pnl = balance['unrealized_pnl']
            margin_ratio = balance['margin_balance'] / balance['total_balance'] if balance['total_balance'] > 0 else 0
            
            # 获取历史PnL计算夏普比率
            pnl_history = await self.client.get_pnl_history()
            sharpe_ratio = self._calculate_sharpe_ratio(pnl_history)
            
            metrics = {
                'total_exposure': total_exposure,
                'leverage': leverage,
                'position_count': position_count,
                'unrealized_pnl': unrealized_pnl,
                'margin_ratio': margin_ratio,
                'current_drawdown': self.current_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'risk_alerts': len(self.risk_alerts)
            }
            
            logger.info(f"风险指标: 杠杆={leverage:.2f}x, 回撤={self.current_drawdown:.2f}%")
            return metrics
            
        except Exception as e:
            logger.error(f"获取风险指标失败: {e}")
            raise
            
    def _calculate_sharpe_ratio(self, pnl_df: pd.DataFrame, risk_free_rate: float = 0.02) -> float:
        """
        计算夏普比率
        
        Args:
            pnl_df: PnL数据
            risk_free_rate: 无风险利率
            
        Returns:
            夏普比率
        """
        try:
            if pnl_df.empty or len(pnl_df) < 2:
                return 0
                
            # 计算日收益率
            pnl_df['daily_return'] = pnl_df['pnl'].pct_change()
            
            # 计算平均收益和标准差
            mean_return = pnl_df['daily_return'].mean()
            std_return = pnl_df['daily_return'].std()
            
            if std_return == 0:
                return 0
                
            # 年化夏普比率
            sharpe = (mean_return - risk_free_rate / 365) / std_return * (365 ** 0.5)
            
            return float(sharpe)
            
        except Exception as e:
            logger.error(f"计算夏普比率失败: {e}")
            return 0
            
    async def emergency_close_all(self) -> List[Dict]:
        """
        紧急平仓所有持仓
        
        Returns:
            平仓订单列表
        """
        try:
            logger.warning("执行紧急平仓")
            
            # 取消所有未完成订单
            await self.client.cancel_all_orders()
            
            # 获取所有持仓
            positions = await self.client.get_account_positions()
            
            # 平仓订单
            close_orders = []
            for pos in positions:
                if pos['size'] != 0:
                    # 确定平仓方向
                    side = 'sell' if pos['side'] == 'buy' else 'buy'
                    
                    try:
                        order = await self.client.place_order(
                            symbol=pos['symbol'],
                            side=side,
                            order_type='market',
                            quantity=abs(pos['size']),
                            reduce_only=True
                        )
                        close_orders.append(order)
                        logger.info(f"紧急平仓: {pos['symbol']} {pos['size']}")
                    except Exception as e:
                        logger.error(f"平仓失败 {pos['symbol']}: {e}")
                        
            return close_orders
            
        except Exception as e:
            logger.error(f"紧急平仓失败: {e}")
            raise