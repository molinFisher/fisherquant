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
