import logging
import polars as pl
from .engine import DuckDBEngine

logger = logging.getLogger(__name__)


class BarRepo:
    @staticmethod
    def save_bars_daily(engine: DuckDBEngine, bars: pl.DataFrame) -> None:
        engine.execute_many(
            """INSERT OR REPLACE INTO bars_daily
               (ticker, trade_date, open, high, low, close, volume, amount, market)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                [
                    r[0], r[1], r[2], r[3],
                    r[4], r[5], r[6], r[7], r[8],
                ]
                for r in bars.iter_rows()
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

    # 所有按 ticker 隔离的表，删除标的时统一级联清理（对应 PRD TC-CONS-008）
    TICKER_TABLES: tuple[str, ...] = (
        "bars_daily", "bars_minute", "corporate_actions",
        "positions", "snapshots",
    )

    @staticmethod
    def delete_symbols(engine: DuckDBEngine, tickers: list[str]) -> int:
        """级联删除若干标的的全部关联数据，返回成功删除的标的数。

        每个标的在一个事务内删除其在所有 ticker 维度表（日线/分钟/复权/持仓/快照）
        中的记录；单个标的失败不影响其余标的。tickers 为空时直接返回 0。
        """
        if not tickers:
            return 0
        deleted = 0
        for t in tickers:
            try:
                with engine.transaction() as conn:
                    for tbl in BarRepo.TICKER_TABLES:
                        conn.execute(f"DELETE FROM {tbl} WHERE ticker = ?", [t])
                deleted += 1
            except Exception as e:
                logger.warning("级联删除标的 %s 失败: %s", t, e)
                continue
        return deleted


class PositionRepo:
    @staticmethod
    def save_snapshot(
        engine: DuckDBEngine, date: str, positions: list[dict]
    ) -> None:
        if not positions:
            return
        required = {"ticker", "quantity", "avg_cost", "close_price", "market_value"}
        for p in positions:
            missing = required - set(p.keys())
            if missing:
                raise KeyError(f"Missing required keys in position snapshot: {missing}")
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
