import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ..event.types import OrderSide, OrderStatus

ORDER_STATUS_TRANSITIONS: dict[OrderStatus, list[OrderStatus]] = {
    OrderStatus.NEW: [
        OrderStatus.PENDING,
        OrderStatus.SUBMITTED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.PENDING: [
        OrderStatus.SUBMITTED,
        OrderStatus.ACKED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.SUBMITTED: [
        OrderStatus.ACKED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.ACKED: [
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.PARTIALLY_FILLED: [
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.FILLED: [],
    OrderStatus.REJECTED: [],
    OrderStatus.CANCELLED: [],
}

TERMINAL_STATUSES: set[OrderStatus] = {
    OrderStatus.FILLED,
    OrderStatus.REJECTED,
    OrderStatus.CANCELLED,
}

_COUNTER: dict[str, int] = {}


def _next_order_id() -> str:
    count = _COUNTER.get("order", 0) + 1
    _COUNTER["order"] = count
    return f"ORD-{count:06d}"


@dataclass
class Order:
    order_id: str
    ticker: str
    market: str
    asset_type: str
    side: OrderSide
    quantity: int
    price: float
    filled_qty: int = 0
    filled_price: float = 0.0
    commission: float = 0.0
    status: OrderStatus = OrderStatus.NEW
    order_type: str = "limit"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    condition_price: float | None = None
    condition_type: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return not self.is_terminal

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        allowed = ORDER_STATUS_TRANSITIONS.get(self.status, [])
        return new_status in allowed


def create_order(
    ticker: str,
    market: str,
    asset_type: str,
    side: OrderSide,
    quantity: int,
    price: float,
    order_type: str = "limit",
    condition_price: float | None = None,
    condition_type: str | None = None,
) -> Order:
    return Order(
        order_id=_next_order_id(),
        ticker=ticker,
        market=market,
        asset_type=asset_type,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        condition_price=condition_price,
        condition_type=condition_type,
    )


def is_terminal_status(status: OrderStatus) -> bool:
    return status in TERMINAL_STATUSES
