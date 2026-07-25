from dataclasses import dataclass, field
from enum import Enum
import time as _time


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    NEW = "new"
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKED = "acked"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class Event:
    timestamp: float = field(default_factory=_time.time)
    __event_type__: str = field(default="event", init=False, repr=False)


@dataclass
class MarketSnapshot(Event):
    __event_type__ = "market_snapshot"
    ticker: str = ""
    market: str = "a_share"
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    pre_close: float = 0.0


@dataclass
class Bar(Event):
    __event_type__ = "bar"
    ticker: str = ""
    market: str = "a_share"
    frequency: str = "1d"
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    amount: float = 0.0
    bar_time: float = 0.0


@dataclass
class Signal(Event):
    __event_type__ = "signal"
    strategy: str = ""
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    limit_price: float = 0.0
    confidence: float = 1.0
    reason: str = ""


@dataclass
class OrderPending(Event):
    __event_type__ = "order_pending"
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    price: float = 0.0
    order_type: str = "limit"
    status: OrderStatus = OrderStatus.PENDING


@dataclass
class OrderAcked(Event):
    __event_type__ = "order_acked"
    order_id: str = ""
    broker_order_id: str = ""


@dataclass
class OrderPartiallyFilled(Event):
    __event_type__ = "order_partially_filled"
    order_id: str = ""
    filled_qty: int = 0
    filled_price: float = 0.0
    remaining_qty: int = 0
    commission: float = 0.0


@dataclass
class OrderFilled(Event):
    __event_type__ = "order_filled"
    order_id: str = ""
    ticker: str = ""
    filled_qty: int = 0
    filled_price: float = 0.0
    commission: float = 0.0


@dataclass
class OrderRejected(Event):
    __event_type__ = "order_rejected"
    order_id: str = ""
    ticker: str = ""
    reason: str = ""


@dataclass
class OrderCancelled(Event):
    __event_type__ = "order_cancelled"
    order_id: str = ""


@dataclass
class PositionUpdate(Event):
    __event_type__ = "position_update"
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    quantity: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    available: int = 0


@dataclass
class RiskAlert(Event):
    __event_type__ = "risk_alert"
    rule: str = ""
    ticker: str | None = None
    severity: str = "WARN"
    message: str = ""


@dataclass
class MarketOpen(Event):
    __event_type__ = "market_open"
    market: str = "a_share"


@dataclass
class MarketClose(Event):
    __event_type__ = "market_close"
    market: str = "a_share"


@dataclass
class MarketMidBreak(Event):
    __event_type__ = "market_mid_break"
    market: str = "a_share"


@dataclass
class MarketMidResume(Event):
    __event_type__ = "market_mid_resume"
    market: str = "a_share"


@dataclass
class DividendEvent(Event):
    __event_type__ = "dividend_event"
    ticker: str = ""
    ex_date: str = ""
    cash_per_share: float = 0.0
    bonus_ratio: float = 0.0


@dataclass
class SplitEvent(Event):
    __event_type__ = "split_event"
    ticker: str = ""
    effective_date: str = ""
    split_ratio: float = 1.0
