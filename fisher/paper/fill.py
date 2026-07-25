from ..event.types import Bar, OrderSide
from ..oms.orders import Order


class FillSimulator:
    def __init__(
        self,
        fill_price_mode: str = "current_close",
        price_limit_ratio: float | None = 0.10,
        min_volume_ratio: float = 0.1,
    ):
        self._mode = fill_price_mode
        self._price_limit_ratio = price_limit_ratio
        self._min_volume_ratio = min_volume_ratio

    def check_fill(self, order: Order, bar: Bar) -> tuple[bool, float]:
        if order.ticker != bar.ticker:
            return False, 0.0

        fill_price = self._get_fill_price(bar)

        if not self._check_price_limit(order, fill_price):
            return False, fill_price

        if bar.volume == 0 or order.quantity > bar.volume * self._min_volume_ratio:
            return False, fill_price

        return True, fill_price

    def _get_fill_price(self, bar: Bar) -> float:
        if self._mode == "next_open":
            return bar.open
        elif self._mode == "current_close":
            return bar.close
        elif self._mode == "vwap":
            if bar.volume > 0:
                return bar.amount / bar.volume
            return bar.close
        elif self._mode == "ohlc4":
            return (bar.open + bar.high + bar.low + bar.close) / 4
        return bar.close

    def _check_price_limit(self, order: Order, fill_price: float) -> bool:
        if self._price_limit_ratio is None:
            return True

        limit_upper = order.price * (1 + self._price_limit_ratio)
        limit_lower = order.price * (1 - self._price_limit_ratio)

        if order.side == OrderSide.BUY:
            return fill_price <= limit_upper
        else:
            return fill_price >= limit_lower
