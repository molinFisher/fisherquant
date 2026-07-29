from abc import ABC, abstractmethod
from typing import Callable
from ..event.types import OrderSide
from ..oms.orders import Order
from ..position.service import PositionService


class PreTradeRule(ABC):
    @abstractmethod
    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        ...


class MaxPositionRule(PreTradeRule):
    def __init__(self, max_pct: float = 0.2):
        self._max_pct = max_pct

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        position_value = 0.0
        if pos_svc is not None:
            existing = pos_svc.get_position(order.ticker)
            if existing is not None:
                position_value = existing["avg_cost"] * existing["quantity"]

        new_value = order.price * order.quantity
        total_value = position_value + new_value
        max_allowed = capital * self._max_pct

        if total_value > max_allowed:
            return False, f"MaxPosition: {total_value:.2f} > {max_allowed:.2f}"
        return True, ""


class DailyLossLimitRule(PreTradeRule):
    def __init__(self, max_loss_pct: float = 0.05):
        self._max_loss_pct = max_loss_pct
        self._cumulative_pnl = 0.0

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        # abs() is used here to compute loss magnitude percentage from
        # the cumulative PnL which may be negative; the sign check below
        # (self._cumulative_pnl < 0) ensures we only trigger on actual losses
        loss_pct = abs(self._cumulative_pnl) / capital if capital > 0 else 0.0
        if self._cumulative_pnl < 0 and loss_pct >= self._max_loss_pct:
            return False, f"DailyLossLimit: daily loss {loss_pct:.2%} >= {self._max_loss_pct:.2%}"
        return True, ""

    def reset_daily_pnl(self) -> None:
        self._cumulative_pnl = 0.0

    def record_pnl(self, pnl: float) -> None:
        self._cumulative_pnl += pnl


class PriceLimitRule(PreTradeRule):
    def __init__(self, upper: float = 0.095, lower: float = -0.095):
        self._upper = upper
        self._lower = lower

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        if market_price <= 0:
            return True, ""
        if not self._check_price_limit(order, market_price):
            side = "up" if order.side == OrderSide.BUY else "down"
            return False, f"PriceLimit: price outside {side} limit"
        return True, ""

    def _check_price_limit(self, order: Order, market_price: float) -> bool:
        pct_change = (market_price - order.price) / order.price if order.price > 0 else 0.0
        if order.side == OrderSide.BUY:
            return pct_change <= self._upper
        else:
            return pct_change >= self._lower


class BlacklistRule(PreTradeRule):
    def __init__(self, blacklist: list[str] | None = None):
        self._blacklist = set(blacklist or [])

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        if order.ticker in self._blacklist:
            return False, f"Blacklist: {order.ticker} is blacklisted"
        return True, ""


class SectorLimitRule(PreTradeRule):
    def __init__(self, max_pct: float = 0.3, sector_map: dict[str, str] | None = None):
        self._max_pct = max_pct
        self._sector_map = sector_map or {}

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        sector = self._sector_map.get(order.ticker)
        if sector is None:
            return True, ""
        sector_exposure = 0.0
        if pos_svc is not None:
            for ticker, pos in pos_svc.get_all_positions().items():
                if self._sector_map.get(ticker) == sector:
                    sector_exposure += pos.get("market_value", 0.0)
        new_exposure = order.price * order.quantity + sector_exposure
        max_allowed = capital * self._max_pct
        if new_exposure > max_allowed:
            return False, f"SectorLimit: sector {sector} exposure {new_exposure:.2f} > {max_allowed:.2f}"
        return True, ""


# ---- 量化系统必备清单 G3：事前风控补全（单笔/名义/总仓位/杠杆/挂单上限）----


class MaxOrderQtyRule(PreTradeRule):
    """单笔最大下单量（防乌龙指 / 流动性冲击）。"""

    def __init__(self, max_qty: int = 100_000):
        self._max_qty = max_qty

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None = None,
        capital: float = 0.0,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        if order.quantity > self._max_qty:
            return False, f"MaxOrderQty: qty {order.quantity} > {self._max_qty}"
        return True, ""


class MaxNotionalRule(PreTradeRule):
    """单笔最大名义金额（价格 × 数量）。优先用市价估算。"""

    def __init__(self, max_notional: float = 10_000_000.0):
        self._max_notional = max_notional

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None = None,
        capital: float = 0.0,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        ref_price = market_price if market_price > 0 else order.price
        notional = ref_price * order.quantity
        if notional > self._max_notional:
            return False, f"MaxNotional: {notional:.2f} > {self._max_notional:.2f}"
        return True, ""


class MaxPositionPerSymbolRule(PreTradeRule):
    """单标的持仓市值上限（含本次委托后的增量）。"""

    def __init__(self, max_value: float = 5_000_000.0):
        self._max_value = max_value

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None = None,
        capital: float = 0.0,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        existing = 0.0
        if pos_svc is not None:
            pos = pos_svc.get_position(order.ticker)
            if pos:
                existing = pos.get("market_value", 0.0) or (
                    pos.get("avg_cost", 0.0) * pos.get("quantity", 0)
                )
        new_value = order.price * order.quantity
        total = existing + new_value
        if total > self._max_value:
            return False, f"MaxPositionPerSymbol: {total:.2f} > {self._max_value:.2f}"
        return True, ""


class MaxLeverageRule(PreTradeRule):
    """总杠杆上限：总敞口（现有持仓市值绝对值 + 本次名义）/ 资金 <= 上限。"""

    def __init__(self, max_leverage: float = 1.0):
        self._max_leverage = max_leverage

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None = None,
        capital: float = 0.0,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        if capital <= 0:
            return True, ""
        gross = 0.0
        if pos_svc is not None:
            for p in pos_svc.get_all_positions().values():
                gross += abs(p.get("market_value", 0.0))
        new_notional = (market_price if market_price > 0 else order.price) * order.quantity
        gross += new_notional
        leverage = gross / capital
        if leverage > self._max_leverage:
            return False, f"MaxLeverage: {leverage:.2f} > {self._max_leverage:.2f}"
        return True, ""


class MaxOpenOrdersRule(PreTradeRule):
    """未成交挂单上限。挂单数通过可注入的 provider 获取（默认 0，等于不限制）。

    说明：回测/模拟交易中实时挂单数来自 PaperEngine，需由调用方注入
    `open_orders_provider`（如 `lambda: len(paper._orders)`）。配置驱动（yaml）下
    无法注入时退化为 0，即不生效；需显式接入才启用。
    """

    def __init__(
        self,
        max_open: int = 50,
        open_orders_provider: Callable[[], int] | None = None,
    ):
        self._max_open = max_open
        self._provider = open_orders_provider or (lambda: 0)

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None = None,
        capital: float = 0.0,
        market_price: float = 0.0,
    ) -> tuple[bool, str]:
        if self._provider() >= self._max_open:
            return False, f"MaxOpenOrders: open orders {self._provider()} >= {self._max_open}"
        return True, ""
