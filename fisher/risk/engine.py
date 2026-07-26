from ..oms.orders import Order
from ..position.service import PositionService
from .pre_trade import PreTradeRule


class RiskEngine:
    def __init__(self, rules: list[PreTradeRule] | None = None):
        self._rules = rules or []

    def check(
        self,
        order: Order,
        pos_svc: PositionService | None,
        capital: float,
        market_price: float = 0.0,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        for rule in self._rules:
            approved, reason = rule.check(order, pos_svc, capital, market_price)
            if not approved and reason:
                reasons.append(reason)
        return len(reasons) == 0, reasons

    def add_rule(self, rule: PreTradeRule) -> None:
        self._rules.append(rule)

    def record_pnl(self, pnl: float) -> None:
        """回测每根 bar 调用，累积日内盈亏（驱动 DailyLossLimit 等规则）。"""
        for rule in self._rules:
            if hasattr(rule, "record_pnl"):
                rule.record_pnl(pnl)

    def reset_daily(self) -> None:
        """新交易日重置日内累计（如 DailyLossLimit）。"""
        for rule in self._rules:
            if hasattr(rule, "reset_daily_pnl"):
                rule.reset_daily_pnl()
