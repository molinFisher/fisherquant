from collections import deque
from ..base import Strategy
from ...event.types import Bar, OrderSide


class RotationalStrategy(Strategy):
    name = "rotational"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._top_n = self.params.get("top_n", 5)
        self._lookback = self.params.get("lookback", 20)
        self._prices: dict[str, deque[float]] = {}

    async def on_bar(self, bar: Bar):
        ticker = bar.ticker
        if ticker not in self._prices:
            self._prices[ticker] = deque(maxlen=self._lookback)
        self._prices[ticker].append(bar.close)

    def generate_signals(self):
        returns: dict[str, float] = {}
        for ticker, prices in self._prices.items():
            if len(prices) >= self._lookback:
                values = list(prices)
                ret = (values[-1] - values[0]) / values[0] if values[0] != 0 else 0.0
                returns[ticker] = ret

        ranked = sorted(returns.items(), key=lambda x: x[1], reverse=True)
        top_picks = ranked[:self._top_n]

        for ticker, ret in top_picks:
            self.emit_signal(ticker, "a_share", OrderSide.BUY, 100, 0.0, min(abs(ret), 1.0), "rotational_top")
