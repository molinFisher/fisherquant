from typing import Any
import threading
import queue
import duckdb
import polars as pl
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class DuckDBManager:
    """Single-write + read-pool DuckDB connection manager.

    Write connection: one connection, write-lock, all DDL/DML.
    Read pool: N read-only connections, concurrent SELECT.
    """
    _instance: "DuckDBManager | None" = None
    _lock = threading.Lock()

    def __new__(cls, path: str = "", read_pool_size: int = 4):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, path: str = "", read_pool_size: int = 4):
        if self._initialized:
            return
        self._path = path
        self._write_lock = threading.RLock()
        self._write_conn: duckdb.DuckDBPyConnection | None = None
        self._read_pool: queue.Queue = queue.Queue()
        self._read_pool_size = read_pool_size
        self._closed = False
        if path:
            self.connect(path, read_pool_size)
        self._initialized = True

    _connect_lock = threading.Lock()

    def connect(self, path: str, read_pool_size: int = 4):
        with self._connect_lock:
            if not self._closed and self._write_conn is not None and self._path == path:
                return
            self._closed = False
            if self._write_conn is not None:
                with self._write_lock:
                    self._write_conn.close()
                    self._write_conn = None
            while not self._read_pool.empty():
                try:
                    self._read_pool.get_nowait().close()
                except queue.Empty:
                    break
            self._path = path
            self._write_conn = duckdb.connect(path)
            self._read_pool_size = read_pool_size
            for _ in range(read_pool_size):
                conn = duckdb.connect(path)
                conn.execute("PRAGMA threads=2")
                self._read_pool.put(conn)

    @property
    def write_connection(self) -> duckdb.DuckDBPyConnection:
        if self._write_conn is None:
            raise RuntimeError("DuckDBManager not connected")
        return self._write_conn

    def execute(self, sql: str, params: list | None = None) -> duckdb.DuckDBPyRelation:
        with self._write_lock:
            return self._write_conn.execute(sql, params or [])

    def execute_many(self, sql: str, params_list: list[list]) -> None:
        with self._write_lock:
            self._write_conn.executemany(sql, params_list)

    def query_df(self, sql: str, params: list | None = None) -> pl.DataFrame:
        conn = self._acquire_read()
        try:
            return conn.sql(sql, params=params or []).pl()
        finally:
            self._read_pool.put(conn)

    @contextmanager
    def transaction(self):
        """Explicit transaction: BEGIN -> work -> COMMIT or ROLLBACK."""
        with self._write_lock:
            self._write_conn.execute("BEGIN")
            try:
                yield self._write_conn
                self._write_conn.execute("COMMIT")
            except Exception:
                self._write_conn.execute("ROLLBACK")
                raise

    def _acquire_read(self) -> duckdb.DuckDBPyConnection:
        timeout = 5
        try:
            return self._read_pool.get(timeout=timeout)
        except queue.Empty:
            logger.warning("Read pool exhausted, creating temp connection")
            return duckdb.connect(self._path)

    def close(self):
        if self._closed:
            return
        with self._write_lock:
            if self._write_conn:
                self._write_conn.close()
                self._write_conn = None
        while not self._read_pool.empty():
            try:
                self._read_pool.get_nowait().close()
            except queue.Empty:
                break
        self._closed = True
        DuckDBManager._instance = None


class DuckDBEngine:
    """Backward-compatible independent connection (preserves old API)."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = duckdb.connect(path)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def execute(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyRelation:
        if params is None:
            params = []
        with self._lock:
            return self._conn.execute(sql, params)

    def execute_many(self, sql: str, params_list: list[list]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_list)

    def query_df(self, sql: str, params: list[Any] | None = None) -> pl.DataFrame:
        if params is None:
            params = []
        with self._lock:
            rel = self._conn.sql(sql, params=params)
            return rel.pl()

    def close(self) -> None:
        self._conn.close()
