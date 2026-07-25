import threading
import duckdb
import polars as pl


class DuckDBEngine:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = duckdb.connect(path)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def execute(self, sql: str, params: list = []) -> duckdb.DuckDBPyRelation:
        return self._conn.execute(sql, params)

    def execute_many(self, sql: str, params_list: list[list]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_list)

    def query_df(self, sql: str, params: list = []) -> pl.DataFrame:
        rel = self._conn.sql(sql, params=params)
        return rel.pl()

    def close(self) -> None:
        self._conn.close()
