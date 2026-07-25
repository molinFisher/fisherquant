from datetime import datetime
from collections import defaultdict
import polars as pl
from ..event.types import Bar


class TimePlayer:
    def __init__(self, bars_df: pl.DataFrame):
        self._df = bars_df.sort("trade_date", "ticker")

    def __iter__(self):
        for row in self._df.iter_rows(named=True):
            dt = datetime.strptime(row["trade_date"], "%Y-%m-%d")
            yield Bar(
                ticker=row["ticker"],
                market=row.get("market", "a_share"),
                frequency=row.get("frequency", "1d"),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                amount=float(row["amount"]),
                bar_time=dt.timestamp(),
            )

    def __len__(self) -> int:
        return self._df.height

    def by_date(self) -> dict[str, list[Bar]]:
        grouped: dict[str, list[Bar]] = defaultdict(list)
        for bar in self:
            date_str = datetime.fromtimestamp(bar.bar_time).strftime("%Y-%m-%d")
            grouped[date_str].append(bar)
        return dict(grouped)

    def filter_ticker(self, ticker: str) -> list[Bar]:
        return [b for b in self if b.ticker == ticker]
