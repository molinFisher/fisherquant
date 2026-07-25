from collections import deque
from ..base import Strategy
from ...event.types import Bar, OrderSide


class PairTradeStrategy(Strategy):
    name = "pair_trade"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ticker_a = self.params.get("ticker_a", "")
        self._ticker_b = self.params.get("ticker_b", "")
        self._window = self.params.get("window", 60)
        self._entry_z = self.params.get("entry_z", 2.0)
        self._prices_a: deque[float] = deque(maxlen=self._window)
        self._prices_b: deque[float] = deque(maxlen=self._window)

    async def on_bar(self, bar: Bar):
        if bar.ticker == self._ticker_a:
            self._prices_a.append(bar.close)
        elif bar.ticker == self._ticker_b:
            self._prices_b.append(bar.close)

        if len(self._prices_a) < self._window or len(self._prices_b) < self._window:
            return

        pa = list(self._prices_a)
        pb = list(self._prices_b)
        spread = [pa[i] - pb[i] for i in range(self._window)]
        spread_mean = sum(spread) / len(spread)
        variance = sum((s - spread_mean) ** 2 for s in spread) / len(spread)
        std = variance ** 0.5

        if std == 0:
            return

        z_score = (spread[-1] - spread_mean) / std

        if z_score > self._entry_z:
            self.emit_signal(self._ticker_a, bar.market, OrderSide.SELL, 100, pa[-1], 0.6, "pair_short_a")
            self.emit_signal(self._ticker_b, bar.market, OrderSide.BUY, 100, pb[-1], 0.6, "pair_long_b")
        elif z_score < -self._entry_z:
            self.emit_signal(self._ticker_a, bar.market, OrderSide.BUY, 100, pa[-1], 0.6, "pair_long_a")
            self.emit_signal(self._ticker_b, bar.market, OrderSide.SELL, 100, pb[-1], 0.6, "pair_short_b")
