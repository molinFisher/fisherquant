import polars as pl
from .registry import FactorRegistry
from ..store.engine import DuckDBEngine


_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS factor_cache (
    ticker VARCHAR NOT NULL,
    trade_date VARCHAR NOT NULL,
    factor_name VARCHAR NOT NULL,
    value DOUBLE NOT NULL,
    PRIMARY KEY (ticker, trade_date, factor_name)
)
"""


class FactorEngine:
    def __init__(self, db_engine: DuckDBEngine | None = None):
        self._db = db_engine
        if self._db:
            self._db.execute(_CACHE_DDL)

    def compute(
        self,
        factor_names: list[str],
        df: pl.DataFrame,
        ticker: str = "",
        date: str = "",
    ) -> pl.DataFrame:
        result = df.clone()
        for fname in factor_names:
            factor = FactorRegistry.get(fname)
            computed = factor.compute(df)
            col = computed[fname]
            result = result.with_columns(col.alias(fname))
            if self._db and ticker:
                self._store_cache(ticker, fname, col, result)
        return result

    def _store_cache(
        self,
        ticker: str,
        factor_name: str,
        col: pl.Series,
        df: pl.DataFrame,
    ) -> None:
        rows = []
        trade_date_col = "trade_date" if "trade_date" in df.columns else None
        for i in range(len(col)):
            val = col[i]
            if val is None:
                continue
            trade_date = df[trade_date_col][i] if trade_date_col else str(i)
            rows.append([ticker, str(trade_date), factor_name, float(val)])
        if rows:
            self._db.execute_many(
                "INSERT OR REPLACE INTO factor_cache (ticker, trade_date, factor_name, value) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
