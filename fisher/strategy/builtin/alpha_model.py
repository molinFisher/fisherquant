from ..base import Strategy
from ...event.types import Bar, OrderSide


class AlphaModelStrategy(Strategy):
    name = "alpha_model"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self._top_n = self.params.get("top_n", 10)
        self._factor_scores: dict[str, float] = {}
        self._signals_sent: set[str] = set()

    async def on_bar(self, bar: Bar):
        pass

    def set_factor_scores(self, scores: dict[str, float]):
        self._factor_scores = scores

    def generate_signals(self):
        sorted_tickers = sorted(self._factor_scores.items(), key=lambda x: x[1], reverse=True)
        top_tickers = sorted_tickers[:self._top_n]
        bottom_tickers = sorted_tickers[-self._top_n:] if len(sorted_tickers) >= self._top_n * 2 else []

        for ticker, score in top_tickers:
            self.emit_signal(ticker, "a_share", OrderSide.BUY, 100, 0.0, min(abs(score), 1.0), "alpha_top")

        for ticker, score in bottom_tickers:
            self.emit_signal(ticker, "a_share", OrderSide.SELL, 100, 0.0, min(abs(score), 1.0), "alpha_bottom")
