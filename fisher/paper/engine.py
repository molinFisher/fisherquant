import random
from threading import RLock
from ..broker.adapter import BrokerAdapter
from ..event.types import Bar, OrderSide, OrderStatus
from ..oms.orders import Order
from ..oms.engine import OMSEngine
from ..market.rules import ExchangeRules
from ..config.schemas import AssetFeeConfig, FeesConfig
from .fees import FeeCalculator
from .fill import FillSimulator


class PaperEngine(BrokerAdapter):
    """仿真券商。

    对应量化系统改进清单的关键修正：
    - P0-2：所有订单延迟一根 bar 成交（信号在 bar N 生成 → 成交在 N+1），
      从根本上消除"同根 K 线看到收盘价又用收盘价成交"的向前看偏差；
    - P0-6：条件单（止损/止盈）由 check_conditions 触发，触发后同样延迟一根 bar 成交；
    - P0-3：滑点经由 FillSimulator 透传；
    - P1-8：allow_short=True 时支持卖空（净头寸可为负）；
    - P2-13：账户状态访问加锁，支持并发/实时路径。
    """

    def __init__(
        self,
        fee_config: AssetFeeConfig | FeesConfig | None = None,
        rules: ExchangeRules | None = None,
        initial_capital: float = 1_000_000.0,
        fill_price_mode: str = "current_close",
        slippage_bps: float = 0.0,
        allow_short: bool = False,
        thread_safe: bool = True,
        cancel_failure_rate: float = 0.0,
        cancel_delay_bars: int = 0,
        rng_seed: int | None = None,
    ):
        self._capital = initial_capital
        self._available = initial_capital
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, dict] = {}
        self._rules = rules
        self._oms = OMSEngine()
        self._allow_short = allow_short
        # G1 MVP：撤单仿真（默认均关闭，向后兼容）
        self._cancel_failure_rate = cancel_failure_rate
        self._cancel_delay_bars = cancel_delay_bars
        self._rng = random.Random(rng_seed) if rng_seed is not None else random
        self._cancel_pending: dict[str, int] = {}
        self._cancel_failures: int = 0

        if isinstance(fee_config, FeesConfig):
            self._fee_calc = FeeCalculator.from_config(fee_config)
        elif isinstance(fee_config, AssetFeeConfig):
            self._fee_calc = FeeCalculator({"default": fee_config})
        else:
            self._fee_calc = None

        self._fill_sim = FillSimulator(
            fill_price_mode=fill_price_mode, slippage_bps=slippage_bps
        )

        # 延迟成交相关状态
        self._deferred: list[Order] = []      # 待下一根 bar 撮合的订单（上一根及之前提交）
        self._pending_new: list[Order] = []    # 本根 bar 内新提交的订单（留到下一根撮合）
        self._open_cond: list[Order] = []      # 已挂出但未触发的条件单
        self._order_bar: dict[str, int] = {}   # order_id -> 提交时的 bar 序号
        self._triggered: dict[str, bool] = {}  # order_id -> 条件是否已触发
        self._bar_index: int = 0
        self._prev_close: dict[str, float] = {}  # ticker -> 上一根收盘价（P2-16 涨跌停判定）

        self._lock = RLock() if thread_safe else None

    def _locked(self):
        # 兼容 thread_safe=False：返回一个 no-op 上下文
        if self._lock is None:
            from contextlib import nullcontext
            return nullcontext()
        return self._lock

    def submit_order(self, order: Order) -> Order:
        if order.order_id in self._orders:
            raise ValueError(f"Order {order.order_id} already submitted")
        with self._locked():
            self._oms.submit(order)
            self._orders[order.order_id] = order
            self._order_bar[order.order_id] = self._bar_index
            self._triggered[order.order_id] = (order.condition_type is None)
            # 本根 bar 提交的订单留到下一根撮合（P0-2：避免同根向前看）
            self._pending_new.append(order)
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.is_terminal:
            return False
        # G1 MVP：撤单失败率（默认 0 → 总是成功，向后兼容）
        if self._cancel_failure_rate > 0 and self._rng.random() < self._cancel_failure_rate:
            self._cancel_failures += 1
            return False
        # G1 MVP：撤单延迟（默认 0 → 立即生效；>0 → N 根 bar 后才真正撤单）
        if self._cancel_delay_bars > 0:
            self._cancel_pending[order_id] = self._cancel_delay_bars
            return True  # 撤单已被接受，延迟生效
        self._oms.cancel(order_id)
        return True

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_positions(self) -> dict[str, dict]:
        with self._locked():
            return dict(self._positions)

    def get_account(self) -> dict:
        with self._locked():
            return {"capital": self._capital, "available": self._available}

    def check_conditions(self, ticker: str, current_price: float) -> list[Order]:
        """评估并触发条件单；被触发的单延迟一根 bar 成交。"""
        with self._locked():
            triggered = self._oms.check_conditions(ticker, current_price)
            for o in triggered:
                self._triggered[o.order_id] = True
                self._order_bar[o.order_id] = self._bar_index
                self._deferred.append(o)
            return triggered

    def on_bar(self, bar: Bar) -> list[Order]:
        with self._locked():
            self._bar_index += 1
            # G1 MVP：处理延迟撤单（倒计时归零才真正撤单；撤单生效前订单仍可成交）
            for oid in list(self._cancel_pending.keys()):
                self._cancel_pending[oid] -= 1
                if self._cancel_pending[oid] <= 0:
                    self._cancel_pending.pop(oid)
                    o = self._orders.get(oid)
                    if o is not None and not o.is_terminal:
                        self._oms.cancel(oid)
            # 仅撮合上一根及之前提交的订单；本根新提交的留到下一根
            eligible = self._deferred
            self._deferred = []
            filled_orders: list[Order] = []

            for order in eligible:
                if order.is_terminal:
                    continue
                if order.ticker != bar.ticker:
                    # 非本标的：保留到该标的下一根 bar
                    self._deferred.append(order)
                    continue
                if order.condition_type is not None and not self._triggered.get(order.order_id, False):
                    self._open_cond.append(order)
                    continue

                fill_result, fill_price = self._fill_sim.check_fill(
                    order, bar, prev_close=self._prev_close.get(bar.ticker)
                )
                if not fill_result:
                    # 未成交（流动性不足/涨跌停/限价）：GTC 下一根重试
                    self._deferred.append(order)
                    continue

                commission = self._compute_commission(order, fill_price)
                self._oms.update_fill(order.order_id, order.quantity, fill_price, commission)
                self._apply_fill(order, fill_price, commission, bar.close)
                filled_orders.append(order)

            # 本根内新提交的订单推到下一根撮合
            self._deferred.extend(self._pending_new)
            self._pending_new = []
            # 记录本根收盘价，供下一根涨跌停判定
            self._prev_close[bar.ticker] = bar.close
            return filled_orders

    def _compute_commission(self, order: Order, fill_price: float) -> float:
        trade_value = fill_price * order.quantity
        if self._fee_calc is None:
            return 0.0
        try:
            fees = self._fee_calc.calculate(order.market, order.side, trade_value, order.quantity)
        except ValueError:
            fees = self._fee_calc.calculate("default", order.side, trade_value, order.quantity)
        return fees["total"]

    def _apply_fill(self, order: Order, fill_price: float, commission: float, close: float) -> None:
        ticker = order.ticker
        is_buy = order.side == OrderSide.BUY
        qty = order.quantity
        trade_value = fill_price * qty

        if ticker not in self._positions:
            self._positions[ticker] = {
                "ticker": ticker, "quantity": 0, "avg_cost": 0.0, "market_value": 0.0,
            }
        pos = self._positions[ticker]
        old_qty = pos["quantity"]
        old_cost = pos["avg_cost"]
        sign = 1 if is_buy else -1

        # P1-8：不允许做空时，卖出超过持仓则截断为仅平多
        if not self._allow_short and old_qty >= 0 and sign < 0 and qty > old_qty:
            qty = old_qty
            if qty <= 0:
                return
            trade_value = fill_price * qty

        new_qty = old_qty + sign * qty

        if new_qty == 0:
            pos["quantity"] = 0
            pos["avg_cost"] = 0.0
        elif (old_qty >= 0 and sign > 0) or (old_qty <= 0 and sign < 0):
            # 同方向：加权平均成本
            base = old_cost * abs(old_qty) + fill_price * qty
            pos["avg_cost"] = base / abs(new_qty) if new_qty != 0 else 0.0
            pos["quantity"] = new_qty
        else:
            # 反方向（平仓 / 反手）
            pos["quantity"] = new_qty
            if abs(sign * qty) > abs(old_qty):
                # 越过零点，剩余为反方向，成本取成交价
                pos["avg_cost"] = fill_price

        pos["market_value"] = pos["quantity"] * close

        if is_buy:
            self._available -= trade_value + commission
        else:
            self._available += trade_value - commission

        self._capital = self._available + sum(p["market_value"] for p in self._positions.values())
