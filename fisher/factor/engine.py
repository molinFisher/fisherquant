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
            try:
                factor = FactorRegistry.get(fname)
            except KeyError:
                raise KeyError(f"Factor '{fname}' not found in registry")
            expected_cols = factor.output_columns

            cached_series = None
            if self._db and ticker:
                cached_series = self._read_cache(ticker, expected_cols, result)

            if cached_series is not None:
                for s in cached_series:
                    result = result.with_columns(s)
                continue

            orig_cols = set(df.columns)
            computed = factor.compute(df)
            added_cols = [c for c in computed.columns if c not in orig_cols]
            for col_name in added_cols:
                result = result.with_columns(computed[col_name].alias(col_name))
            if self._db and ticker:
                self._store_cache(ticker, {c: result[c] for c in added_cols}, result)
        return result

    def _read_cache(
        self,
        ticker: str,
        col_names: list[str],
        df: pl.DataFrame,
    ) -> list[pl.Series] | None:
        if "trade_date" not in df.columns:
            return None
        series_list = []
        for col_name in col_names:
            cached = self._db.query_df(
                "SELECT trade_date, value FROM factor_cache WHERE ticker=? AND factor_name=?",
                [ticker, col_name],
            )
            if cached.is_empty():
                return None
            date_map = {}
            for row in cached.iter_rows():
                date_map[row[0]] = row[1]
            values = []
            for i in range(len(df)):
                td = str(df["trade_date"][i])
                if td not in date_map:
                    return None
                values.append(date_map[td])
            series_list.append(pl.Series(col_name, values))
        return series_list

    def _store_cache(
        self,
        ticker: str,
        columns: dict[str, pl.Series],
        df: pl.DataFrame,
    ) -> None:
        if "trade_date" not in df.columns:
            return
        for factor_name, col in columns.items():
            rows = []
            for i in range(len(col)):
                val = col[i]
                if val is None:
                    continue
                trade_date = df["trade_date"][i]
                rows.append([ticker, str(trade_date), factor_name, float(val)])
            if rows:
                self._db.execute_many(
                    "INSERT OR REPLACE INTO factor_cache (ticker, trade_date, factor_name, value) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
