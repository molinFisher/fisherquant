from collections import deque
from ..base import Strategy
from ...event.types import Bar, OrderSide


class PairTradeStrategy(Strategy):
    name = "pair_trade"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._ticker_a = self.params.get("ticker_a", "")
        self._ticker_b = self.params.get("ticker_b", "")
        self._market_a = self.params.get("market_a", "a_share")
        self._market_b = self.params.get("market_b", "a_share")
        self._window = self.params.get("window", 60)
        self._entry_z = self.params.get("entry_z", 2.0)
        self._exit_z = self.params.get("exit_z", 0.5)
        self._prices_a: deque[float] = deque(maxlen=self._window)
        self._prices_b: deque[float] = deque(maxlen=self._window)
        self._position: str | None = None

    async def on_bar(self, bar: Bar):
        if bar.ticker == self._ticker_a:
            self._prices_a.append(bar.close)
            self._market_a = bar.market or self._market_a
        elif bar.ticker == self._ticker_b:
            self._prices_b.append(bar.close)
            self._market_b = bar.market or self._market_b

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

        if self._position == "short_a":
            if abs(z_score) <= self._exit_z:
                self._position = None
                self.emit_signal(self._ticker_a, self._market_a, OrderSide.BUY, 100, pa[-1], 0.6, "pair_exit_short_a")
                self.emit_signal(self._ticker_b, self._market_b, OrderSide.SELL, 100, pb[-1], 0.6, "pair_exit_long_b")
            return
        elif self._position == "long_a":
            if abs(z_score) <= self._exit_z:
                self._position = None
                self.emit_signal(self._ticker_a, self._market_a, OrderSide.SELL, 100, pa[-1], 0.6, "pair_exit_long_a")
                self.emit_signal(self._ticker_b, self._market_b, OrderSide.BUY, 100, pb[-1], 0.6, "pair_exit_short_b")
            return

        if z_score > self._entry_z:
            self._position = "short_a"
            self.emit_signal(self._ticker_a, self._market_a, OrderSide.SELL, 100, pa[-1], 0.6, "pair_short_a")
            self.emit_signal(self._ticker_b, self._market_b, OrderSide.BUY, 100, pb[-1], 0.6, "pair_long_b")
        elif z_score < -self._entry_z:
            self._position = "long_a"
            self.emit_signal(self._ticker_a, self._market_a, OrderSide.BUY, 100, pa[-1], 0.6, "pair_long_a")
            self.emit_signal(self._ticker_b, self._market_b, OrderSide.SELL, 100, pb[-1], 0.6, "pair_short_b")
