from typing import Any
import os
import threading
import time
import queue
import shutil
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
        """打开（或重建）数据库。

        - 并发保护：_connect_lock 确保同一时刻仅一个协程执行 reconnect。
        - 重入保护：若已连接同一路径则直接返回，避免重复开销。
        - 先关闭旧句柄再连接，防止 R2 单例写向已失效的死连接。
        - 若文件损坏导致连接/首查询失败，自动备份损坏文件并以空库重建
          （对应 PRD §16.13 损坏 DuckDB 自恢复），连接过程本身不向外抛异常。
        """
        with self._connect_lock:
            # 已连接到同路径 → 复用现有连接
            if not self._closed and self._write_conn is not None and self._path == path:
                return

            self._closed = False
            self._path = path
            self._read_pool_size = read_pool_size

            # 关闭旧句柄（含异常保护）
            self._close_write_locked()
            self._drain_read_pool_locked()

            try:
                self._write_conn = duckdb.connect(path)
                self._write_conn.execute("SELECT 1")  # 探针
            except Exception as e:
                logger.warning("DuckDB 连接/校验失败 %s (%s)，尝试备份并重建", path, e)
                self._rebuild_and_reconnect_locked(path)

            # 重建读连接池
            for _ in range(read_pool_size):
                try:
                    conn = duckdb.connect(path)
                    conn.execute("PRAGMA threads=2")
                    # DuckDB 读连接默认即为 autocommit：每次 SELECT 立即提交并释放快照，
                    # 因此读连接不会长期持有快照阻塞写连接的 checkpoint（避免读写死锁）。
                    # 注：本环境 DuckDB 版本不支持 PRAGMA auto_commit（会抛 CatalogException），
                    # 故不再显式设置——默认 autocommit 即满足需求。
                    self._read_pool.put(conn)
                except Exception as e:
                    logger.warning("读连接池创建失败: %s", e)
                    break

    @classmethod
    def safe_connect(cls, path: str, read_pool_size: int = 4) -> "DuckDBManager":
        """获取（复用单例）管理器并确保底层库可用；损坏文件会自恢复。

        供启动时调用，保证即使遇到损坏的 DuckDB 文件，返回的管理器也已
        指向可用的（已重建的）数据库。
        """
        mgr = cls(path, read_pool_size)
        mgr.connect(path, read_pool_size=read_pool_size)
        return mgr

    def _close_write_locked(self):
        if self._write_conn is not None:
            try:
                self._write_conn.close()
            except Exception:
                pass
            self._write_conn = None

    def _drain_read_pool_locked(self):
        while not self._read_pool.empty():
            try:
                conn = self._read_pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
            except Exception:
                pass

    def _rebuild_and_reconnect_locked(self, path: str):
        """在持锁状态下备份损坏文件并重建空库（调用方需持有 _connect_lock）。"""
        corrupt_backup = f"{path}.corrupt.{int(time.time() * 1000)}"
        try:
            if os.path.exists(path):
                shutil.move(path, corrupt_backup)
                logger.info("损坏的 DuckDB 已备份至 %s", corrupt_backup)
        except OSError:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._write_conn = duckdb.connect(path)

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
        # 每次查询使用独立临时连接并立即关闭，避免读连接持有快照阻塞写连接
        # （DuckDB：读连接未释放快照时会阻塞同一库的写入，导致死锁）。
        conn = duckdb.connect(self._path)
        try:
            return conn.sql(sql, params=params or []).pl()
        finally:
            try:
                conn.close()
            except Exception:
                pass

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

    @contextmanager
    def transaction(self):
        """显式事务：BEGIN -> 工作 -> COMMIT 或 ROLLBACK。

        直接操作底层连接（非 self.execute），避免在已持有 _lock 的事务内
        再次调用 self.execute 造成重入死锁。
        """
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
