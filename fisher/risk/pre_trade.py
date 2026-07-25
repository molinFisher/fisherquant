from abc import ABC, abstractmethod
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
    ) -> tuple[bool, str]:
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
    ) -> tuple[bool, str]:
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
    ) -> tuple[bool, str]:
        if order.ticker in self._blacklist:
            return False, f"Blacklist: {order.ticker} is blacklisted"
        return True, ""
