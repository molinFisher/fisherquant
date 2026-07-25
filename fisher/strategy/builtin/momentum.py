from collections import deque
from ..base import Strategy
from ...event.types import Bar, OrderSide


class MomentumStrategy(Strategy):
    name = "momentum"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._fast_window = max(self.params.get("fast_window", 5), 1)
        self._slow_window = max(self.params.get("slow_window", 20), 2)
        self._prices: dict[str, deque[float]] = {}

    async def on_bar(self, bar: Bar):
        ticker = bar.ticker
        if ticker not in self._prices:
            self._prices[ticker] = deque(maxlen=self._slow_window + 1)
        self._prices[ticker].append(bar.close)

        prices = self._prices[ticker]
        if len(prices) < self._slow_window + 1:
            return

        prices_list = list(prices)
        fast_sma = sum(prices_list[-self._fast_window:]) / self._fast_window
        slow_sma = sum(prices_list[-self._slow_window:]) / self._slow_window
        prev_fast_sma = sum(prices_list[-(self._fast_window + 1):-1]) / self._fast_window
        prev_slow_sma = sum(prices_list[-(self._slow_window + 1):-1]) / self._slow_window

        if prev_fast_sma <= prev_slow_sma and fast_sma > slow_sma:
            self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.8, "momentum_golden_cross")
        elif prev_fast_sma >= prev_slow_sma and fast_sma < slow_sma:
            self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.8, "momentum_death_cross")
