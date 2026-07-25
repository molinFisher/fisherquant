from abc import ABC, abstractmethod
from ..event.types import Bar, Signal, OrderFilled, OrderSide


class Strategy(ABC):
    name: str = "base_strategy"

    def __init__(self, params: dict | None = None):
        self.params = params or {}
        self._signals: list[Signal] = []

    async def on_init(self):
        pass

    @abstractmethod
    async def on_bar(self, bar: Bar):
        ...

    def on_signal(self) -> list[Signal]:
        signals = self._signals[:]
        self._signals.clear()
        return signals

    async def on_order_filled(self, order: OrderFilled):
        pass

    async def on_risk_close(self, order: OrderFilled):
        pass

    def serialize_state(self) -> dict:
        return {"params": self.params}

    def restore_state(self, state: dict):
        self.params = state.get("params", {})

    def emit_signal(
        self,
        ticker: str,
        market: str,
        side: OrderSide,
        quantity: int,
        price: float = 0.0,
        confidence: float = 1.0,
        reason: str = "",
    ):
        self._signals.append(
            Signal(
                strategy=self.name,
                ticker=ticker,
                market=market,
                side=side,
                quantity=quantity,
                limit_price=price,
                confidence=confidence,
                reason=reason,
            )
        )
