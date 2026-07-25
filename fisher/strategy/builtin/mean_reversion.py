from collections import deque
import math
from ..base import Strategy
from ...event.types import Bar, OrderSide


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._window = self.params.get("window", 20)
        self._std_mult = self.params.get("std_mult", 2.0)
        self._prices: dict[str, deque[float]] = {}
        self._last_state: dict[str, str | None] = {}

    async def on_bar(self, bar: Bar):
        ticker = bar.ticker
        if ticker not in self._prices:
            self._prices[ticker] = deque(maxlen=self._window)
            self._last_state[ticker] = None
        self._prices[ticker].append(bar.close)

        prices = self._prices[ticker]
        if len(prices) < self._window:
            return

        values = list(prices)
        sma = sum(values) / len(values)
        variance = sum((v - sma) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)
        lower_band = sma - self._std_mult * std
        upper_band = sma + self._std_mult * std

        current_state = None
        if bar.close <= lower_band:
            current_state = "oversold"
        elif bar.close >= upper_band:
            current_state = "overbought"
        else:
            current_state = "neutral"

        if current_state != self._last_state.get(ticker):
            if current_state == "oversold":
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.7, "mean_reversion_oversold")
            elif current_state == "overbought":
                self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.7, "mean_reversion_overbought")
            self._last_state[ticker] = current_state
