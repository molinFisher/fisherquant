from ..base import Strategy
from ...event.types import Bar, OrderFilled


class CompositeStrategy(Strategy):
    name = "composite"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._strategies: list[Strategy] = []

    def add_strategy(self, strategy: Strategy):
        self._strategies.append(strategy)

    async def on_init(self):
        for s in self._strategies:
            await s.on_init()

    async def on_bar(self, bar: Bar):
        for s in self._strategies:
            await s.on_bar(bar)

    def on_signal(self) -> list:
        signals = []
        for s in self._strategies:
            signals.extend(s.on_signal())
        return signals

    async def on_order_filled(self, order: OrderFilled):
        for s in self._strategies:
            await s.on_order_filled(order)

    def serialize_state(self) -> dict:
        base = super().serialize_state()
        base["strategies"] = [s.serialize_state() for s in self._strategies]
        return base

    def restore_state(self, state: dict):
        super().restore_state(state)
        for i, s_state in enumerate(state.get("strategies", [])):
            if i < len(self._strategies):
                self._strategies[i].restore_state(s_state)
