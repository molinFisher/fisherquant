import polars as pl
from .engine import DuckDBEngine


class BarRepo:
    @staticmethod
    def save_bars_daily(engine: DuckDBEngine, bars: pl.DataFrame) -> None:
        existing = bars.to_dicts()
        engine.execute_many(
            """INSERT OR REPLACE INTO bars_daily
               (ticker, trade_date, open, high, low, close, volume, amount, market)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                [
                    r["ticker"], r["trade_date"], r["open"], r["high"],
                    r["low"], r["close"], r["volume"], r["amount"], r["market"],
                ]
                for r in existing
            ],
        )

    @staticmethod
    def get_bars_daily(
        engine: DuckDBEngine, tickers: list[str], start: str, end: str
    ) -> pl.DataFrame:
        if not tickers:
            return pl.DataFrame()
        placeholders = ",".join(["?"] * len(tickers))
        return engine.query_df(
            f"""SELECT * FROM bars_daily
                WHERE ticker IN ({placeholders})
                  AND trade_date >= ?
                  AND trade_date <= ?
                ORDER BY ticker, trade_date""",
            [*tickers, start, end],
        )


class PositionRepo:
    @staticmethod
    def save_snapshot(
        engine: DuckDBEngine, date: str, positions: list[dict]
    ) -> None:
        if not positions:
            return
        engine.execute_many(
            """INSERT OR REPLACE INTO position_snapshots
               (date, ticker, market, quantity, avg_cost, close_price, market_value)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                [
                    date, p["ticker"], p.get("market", "a_share"),
                    p["quantity"], p["avg_cost"],
                    p["close_price"], p["market_value"],
                ]
                for p in positions
            ],
        )

    @staticmethod
    def get_snapshots(
        engine: DuckDBEngine, start: str, end: str
    ) -> pl.DataFrame:
        return engine.query_df(
            """SELECT * FROM position_snapshots
               WHERE date >= ? AND date <= ?
               ORDER BY date, ticker""",
            [start, end],
        )
