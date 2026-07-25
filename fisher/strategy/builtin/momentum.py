from collections import deque
from ..base import Strategy
from ...event.types import Bar, OrderSide


class MomentumStrategy(Strategy):
    name = "momentum"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._fast_window = self.params.get("fast_window", 5)
        self._slow_window = self.params.get("slow_window", 20)
        self._prices: dict[str, deque[float]] = {}

    async def on_bar(self, bar: Bar):
        ticker = bar.ticker
        if ticker not in self._prices:
            self._prices[ticker] = deque(maxlen=self._slow_window)
        self._prices[ticker].append(bar.close)

        prices = self._prices[ticker]
        if len(prices) < self._slow_window:
            return

        fast_prices = list(prices)[-self._fast_window:]
        slow_prices = list(prices)
        fast_sma = sum(fast_prices) / len(fast_prices)
        slow_sma = sum(slow_prices) / len(slow_prices)

        prev_fast_prices = list(prices)[-(self._fast_window + 1):-1]
        prev_slow_prices = list(prices)[:(self._slow_window - 1)]
        if len(prev_fast_prices) < self._fast_window:
            return
        prev_fast_sma = sum(prev_fast_prices) / len(prev_fast_prices)
        prev_slow_sma = sum(prev_slow_prices) / (self._slow_window - 1)

        if prev_fast_sma <= prev_slow_sma and fast_sma > slow_sma:
            self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.8, "momentum_golden_cross")
        elif prev_fast_sma >= prev_slow_sma and fast_sma < slow_sma:
            self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.8, "momentum_death_cross")
