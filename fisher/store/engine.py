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

# DuckDB 被其他进程持有独占锁时的报错特征（IOException 文案）。
# 锁冲突 ≠ 文件损坏，识别到这些特征时绝不能走「备份重建空库」恢复路径。
_LOCK_CONFLICT_MARKERS = (
    "could not set lock",
    "conflicting lock",
    "lock on file",
    "being used by another process",
)


def _is_lock_conflict(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(m in msg for m in _LOCK_CONFLICT_MARKERS)


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
                if _is_lock_conflict(e):
                    # 另一进程正持有 DuckDB 独占锁（如 Flask reloader 双进程、
                    # 外部诊断脚本）。这不是文件损坏，绝不能走重建——否则会把
                    # 好库挪成 .corrupt 并建空库，清空全部缓存与标的字典。
                    logger.error(
                        "DuckDB 文件被其他进程锁定，拒绝重建以保护数据: %s", e)
                    raise
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

    @staticmethod
    def _is_lock_conflict_exc(e: BaseException) -> bool:
        return _is_lock_conflict(e)

    def _rebuild_and_reconnect_locked(self, path: str):
        """在持锁状态下从 WAL 损坏中恢复，尽量保留已提交数据（PRD §16.13 损坏自恢复）。

        核心约束：**绝不自动清空缓存**。历史上策略 2 会把主库 move 到 .corrupt 并
        新建空库，导致每次重启因残留损坏 WAL 而清空全部缓存与标的字典（累计 9 次
        .corrupt 备份）。现改为：
          - 策略 1：仅丢弃损坏的 WAL、保留主库文件重新打开（保留已提交数据）。
          - 策略 2：主库本身不可读时，**保留原文件、抛出异常**，由上层告警——
            绝不 move/删除主库、绝不建空库。已提交数据不丢，运维可从 .corrupt
            历史备份手动恢复。
        """
        wal_path = f"{path}.wal"
        # 策略 1：丢弃损坏 WAL，保留主库已提交数据
        if os.path.exists(wal_path):
            try:
                os.remove(wal_path)
            except OSError:
                pass
            try:
                self._write_conn = duckdb.connect(path)
                self._write_conn.execute("SELECT 1")  # 探针
                logger.info("已丢弃损坏 WAL 并以主库文件恢复连接（保留已提交数据）")
                return
            except Exception as e:
                logger.warning("丢弃 WAL 后仍无法以读写方式打开主库: %s", e)
        # 策略 2：主库本身不可读——严禁自动建空库清空缓存！
        # 先用只读方式确认是否真损坏；无论结果都保留原文件，抛出异常交由上层告警。
        try:
            probe = duckdb.connect(path, read_only=True)
            probe.execute("SELECT 1")
            probe.close()
            # 只读可开但读写失败（权限/残留锁等）：再试一次读写连接
            self._write_conn = duckdb.connect(path)
            self._write_conn.execute("SELECT 1")
            logger.info("主库以读写方式恢复连接（保留已提交数据）")
            return
        except Exception as e:
            logger.error(
                "DuckDB 主库无法打开，拒绝重建空库以免清空缓存；原文件已保留: %s | %s",
                path, e)
            raise RuntimeError(
                f"DuckDB 主库损坏且无法在本进程恢复，已保留原文件（未清空缓存）：{path}"
            ) from e

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
        # 复用读连接池（连接数有界 = 1 写 + read_pool_size 读），不再每次查询新建
        # 独立句柄。历史上 query_df 每次 duckdb.connect(path) 新建句柄，叠加单写连接
        # 形成「多句柄并发写同一文件」，易引发 WAL/文件损坏，重启时主库不可读进而被
        # 误判损坏并清空缓存（累计 9 次 .corrupt 备份）。复用连接池消除该隐患。
        conn = self._acquire_read()
        try:
            return conn.sql(sql, params=params or []).pl()
        finally:
            try:
                self._read_pool.put(conn)
            except Exception:
                # 放回失败（连接异常）则丢弃，避免污染连接池
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
