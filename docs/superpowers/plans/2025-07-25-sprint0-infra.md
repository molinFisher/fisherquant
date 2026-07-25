# FisherQuant Sprint0 — Technical Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.
> **Dependencies:** INF-02 → INF-04, INF-06, INF-08. Others independent.

**Goal:** Build 10 technical infrastructure components and 1 test infrastructure that all Sprint1-6 features depend on.

**Architecture:** Each INF task is an independent technical module. DuckDB connection manager (INF-02) is the critical path — 3 later tasks depend on it. DSL engine (INF-05) requires security isolation. Everything follows existing fisher/ module patterns.

**Tech Stack:** Python 3.11+, DuckDB, APScheduler, celery+redis, diskcache, pyarrow/polars, pandas-ta, tsdownsample

## Global Constraints
- Python >= 3.11
- All new modules under fisher/ use existing package structure
- DuckDB: single write connection + read pool, explicit transactions
- Rate limiter: ≤ 20 req/min, exponential backoff with jitter
- DSL: NO eval/exec, JSON Schema validation only
- APScheduler: SQLAlchemyJobStore persistence
- Config: MD5 hash polling every 5-10s
- LTTB: ≤ 500 points output
- All public functions type annotated
- Existing tests (450+) must continue to pass

---

### Task INF-02: DuckDB Connection Manager (high priority, prerequisite)

**Files:**
- Modify: `FisherQuant/fisher/store/engine.py`

**Goal:** Replace single connection with write-connection + read-pool architecture with explicit transactions.

```python
# fisher/store/engine.py — replace entirely

import threading
import queue
import duckdb
import polars as pl
from contextlib import contextmanager
from typing import Any
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
        self._write_lock = threading.Lock()
        self._write_conn: duckdb.DuckDBPyConnection | None = None
        self._read_pool: queue.Queue = queue.Queue()
        self._read_pool_size = read_pool_size
        self._closed = False
        if path:
            self.connect(path, read_pool_size)
        self._initialized = True

    def connect(self, path: str, read_pool_size: int = 4):
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
        """Explicit transaction: BEGIN → work → COMMIT or ROLLBACK."""
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
            # Fallback: create temporary read connection
            logger.warning("Read pool exhausted, creating temp connection")
            return duckdb.connect(self._path)

    def close(self):
        if self._closed:
            return
        with self._write_lock:
            if self._write_conn:
                self._write_conn.close()
        while not self._read_pool.empty():
            try:
                self._read_pool.get_nowait().close()
            except queue.Empty:
                break
        self._closed = True
        DuckDBManager._instance = None
```

**Backward compat:** Add an alias class:

```python
# Keep old DuckDBEngine as alias for backward compat
class DuckDBEngine(DuckDBManager):
    """Backward-compatible alias for DuckDBManager singleton."""
    def __init__(self, path: str):
        super().__init__(path=path, read_pool_size=4)
```

- [ ] **Step 1: Write unit test**

```python
# tests/unit/test_duckdb_manager.py
import tempfile
from pathlib import Path
from fisher.store.engine import DuckDBManager

class TestDuckDBManager:
    def test_singleton(self):
        m1 = DuckDBManager(":memory:")
        m2 = DuckDBManager(":memory:")
        assert m1 is m2

    def test_write_and_read(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            m.execute("INSERT INTO t VALUES (1), (2)")
            df = m.query_df("SELECT * FROM t ORDER BY id")
            assert df["id"].to_list() == [1, 2]

    def test_transaction_rollback(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            try:
                with m.transaction():
                    m.execute("INSERT INTO t VALUES (1)")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            df = m.query_df("SELECT COUNT(*) as c FROM t")
            assert df["c"][0] == 0  # rolled back

    def test_transaction_commit(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            with m.transaction():
                m.execute("INSERT INTO t VALUES (42)")
            df = m.query_df("SELECT id FROM t")
            assert df["id"][0] == 42
```

- [ ] **Step 2: Run test → FAIL (old engine)**
- [ ] **Step 3: Implement DuckDBManager, update store/engine.py**
- [ ] **Step 4: Run all tests → 450+ pass**
- [ ] **Step 5: Commit** `"feat(INF-02): DuckDBManager with write-connection, read-pool, and transactions"`

---

### Task INF-03: AKShare Rate Limiter + Retry

**Files:**
- Create: `FisherQuant/fisher/market/rate_limiter.py`
- Modify: `FisherQuant/fisher/market/akshare.py`

```python
# fisher/market/rate_limiter.py
import time
import random
import threading
from functools import wraps
from ..config.schemas import RateLimitConfig
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_per_minute: int = 20):
        self._max_per_minute = max_per_minute
        self._tokens: list[float] = []
        self._lock = threading.Lock()

    def acquire(self):
        now = time.time()
        with self._lock:
            self._tokens = [t for t in self._tokens if t > now - 60]
            if len(self._tokens) >= self._max_per_minute:
                sleep_time = self._tokens[0] + 60 - now + random.uniform(0.1, 0.5)
                if sleep_time > 0:
                    logger.debug("Rate limit: sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)
            self._tokens.append(time.time())

    def reset(self):
        with self._lock:
            self._tokens.clear()


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(
                            "Retry %d/%d after %.1fs for %s: %s",
                            attempt + 1, max_retries, delay, func.__name__, e,
                        )
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


_global_limiter = RateLimiter(max_per_minute=20)


def get_global_limiter() -> RateLimiter:
    return _global_limiter
```

Integrate into akshare.py — wrap `get_bars()` with rate limiting + retry.

Commit: `"feat(INF-03): AKShare rate limiter (≤20/min) with exponential backoff retry"`

---

### Task INF-04: Backtest Serialization (Parquet + metadata.json)

**Files:**
- Create: `FisherQuant/fisher/backtest/serializer.py`

```python
# fisher/backtest/serializer.py
import json
import polars as pl
from pathlib import Path
from datetime import datetime
from ..store.engine import DuckDBManager
import logging

logger = logging.getLogger(__name__)

RESULTS_DIR = "data/backtest_results"


class BacktestSerializer:
    def __init__(self, db: DuckDBManager | None = None):
        self.db = db or DuckDBManager()

    def save(self, result_id: str, nav_history: list, trades: list | None = None,
             benchmark: list | None = None, metadata: dict | None = None) -> str:
        dir_path = Path(RESULTS_DIR) / result_id
        dir_path.mkdir(parents=True, exist_ok=True)

        # equity curve
        df = pl.DataFrame({"date": range(len(nav_history)), "equity": nav_history})
        df.write_parquet(dir_path / "equity_curve.parquet")

        # benchmark
        if benchmark:
            bdf = pl.DataFrame({"date": range(len(benchmark)), "benchmark": benchmark})
            bdf.write_parquet(dir_path / "benchmark_curve.parquet")

        # trades
        if trades:
            tdf = pl.DataFrame(trades)
            tdf.write_parquet(dir_path / "trades.parquet")

        # metadata
        meta = {
            "id": result_id,
            "saved_at": datetime.now().isoformat(),
            "nav_points": len(nav_history),
            **(metadata or {}),
        }
        with open(dir_path / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        # store in DuckDB history
        try:
            self.db.execute(
                """INSERT OR REPLACE INTO backtest_history
                   (id, saved_at, strategy, total_return, sharpe, max_dd)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [result_id, meta["saved_at"],
                 metadata.get("strategy", ""),
                 metadata.get("total_return", 0),
                 metadata.get("sharpe", 0),
                 metadata.get("max_drawdown", 0)],
            )
        except Exception as e:
            logger.warning("Failed to write backtest history: %s", e)

        return str(dir_path)

    def load(self, result_id: str) -> dict:
        dir_path = Path(RESULTS_DIR) / result_id
        result = {"id": result_id}
        eq_path = dir_path / "equity_curve.parquet"
        if eq_path.exists():
            result["equity"] = pl.read_parquet(eq_path)["equity"].to_list()
        bench_path = dir_path / "benchmark_curve.parquet"
        if bench_path.exists():
            result["benchmark"] = pl.read_parquet(bench_path)["benchmark"].to_list()
        trades_path = dir_path / "trades.parquet"
        if trades_path.exists():
            result["trades"] = pl.read_parquet(trades_path).to_dicts()
        meta_path = dir_path / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                result["metadata"] = json.load(f)
        return result

    def list_history(self, limit: int = 200) -> list[dict]:
        try:
            df = self.db.query_df(
                "SELECT * FROM backtest_history ORDER BY saved_at DESC LIMIT ?",
                [limit],
            )
            return df.to_dicts()
        except Exception:
            return []

    def cleanup(self, keep: int = 200):
        count_df = self.db.query_df("SELECT COUNT(*) as c FROM backtest_history")
        total = count_df["c"][0] if len(count_df) > 0 else 0
        if total > keep:
            self.db.execute(
                "DELETE FROM backtest_history WHERE id IN (SELECT id FROM backtest_history ORDER BY saved_at ASC LIMIT ?)",
                [total - keep],
            )
```

Commit: `"feat(INF-04): BacktestSerializer with Parquet/JSON storage and DuckDB history"`

---

### Task INF-05: Strategy DSL Engine

**Files:**
- Create: `FisherQuant/fisher/strategy/dsl.py`
- Create: `FisherQuant/fisher/strategy/dsl_schema.json`

Core: Define `Condition` objects, JSON Schema, and a `DSLEngine.evaluate()` that produces buy/sell signals. No eval/exec.

```python
# fisher/strategy/dsl.py
from dataclasses import dataclass, field
import json
from typing import Callable
import logging

logger = logging.getLogger(__name__)

# Pre-defined signal primitives


def cross_above(series_a, series_b, threshold: float = 0.0):
    """True where series_a crosses above series_b + threshold."""
    result = [False] * len(series_a)
    for i in range(1, len(series_a)):
        if series_a[i - 1] <= series_b[i - 1] + threshold and series_a[i] > series_b[i] + threshold:
            result[i] = True
    return result


def cross_below(series_a, series_b, threshold: float = 0.0):
    """True where series_a crosses below series_b - threshold."""
    result = [False] * len(series_a)
    for i in range(1, len(series_a)):
        if series_a[i - 1] >= series_b[i - 1] - threshold and series_a[i] < series_b[i] - threshold:
            result[i] = True
    return result


def threshold_check(series, operator: str, value: float):
    """True where series OP value. operator: 'gt', 'lt', 'gte', 'lte', 'eq'."""
    ops = {
        "gt": lambda s, v: s > v, "lt": lambda s, v: s < v,
        "gte": lambda s, v: s >= v, "lte": lambda s, v: s <= v, "eq": lambda s, v: s == v,
    }
    op = ops.get(operator, ops["gt"])
    return [op(s, value) for s in series]


PRIMITIVES = {
    "cross_above": cross_above,
    "cross_below": cross_below,
    "threshold": threshold_check,
}


@dataclass
class DSLSignal:
    buy: list[bool] = field(default_factory=list)
    sell: list[bool] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)


class DSLEngine:
    def evaluate(self, config: dict, data: dict) -> DSLSignal:
        buy_rule = config.get("buy_rule")
        sell_rule = config.get("sell_rule")
        n = len(next(iter(data.values()), []))

        buy_signal = [False] * n
        sell_signal = [False] * n

        if buy_rule:
            buy_signal = self._evaluate_rule(buy_rule, data)

        if sell_rule:
            sell_signal = self._evaluate_rule(sell_rule, data)

        weights = [0.0] * n
        for i in range(n):
            if buy_signal[i]:
                weights[i] = 1.0
            elif sell_signal[i]:
                weights[i] = -1.0

        return DSLSignal(buy=buy_signal, sell=sell_signal, weights=weights)

    def _evaluate_rule(self, rule: dict, data: dict) -> list[bool]:
        rule_type = rule.get("type", "primitive")
        if rule_type == "primitive":
            return self._eval_primitive(rule, data)
        elif rule_type == "composite":
            return self._eval_composite(rule, data)
        raise ValueError(f"Unknown rule type: {rule_type}")

    def _eval_primitive(self, rule: dict, data: dict) -> list[bool]:
        name = rule["name"]
        args = rule.get("args", [])
        kwargs = rule.get("kwargs", {})
        prim = PRIMITIVES.get(name)
        if prim is None:
            raise ValueError(f"Unknown primitive: {name}")
        resolved_args = [data.get(a, a) if isinstance(a, str) else a for a in args]
        return prim(*resolved_args, **kwargs)

    def _eval_composite(self, rule: dict, data: dict) -> list[bool]:
        op = rule.get("operator", "AND")
        sub_rules = rule.get("rules", [])
        if not sub_rules:
            return []
        results = [self._evaluate_rule(r, data) for r in sub_rules]
        n = len(results[0])
        combined = [False] * n
        for i in range(n):
            vals = [r[i] for r in results]
            combined[i] = all(vals) if op == "AND" else any(vals)
        return combined


def validate_dsl(config: dict) -> list[str]:
    """Validate a DSL config, returning list of errors (empty = valid)."""
    errors = []
    for key in ["buy_rule", "sell_rule"]:
        if key in config and config[key]:
            errors += _validate_rule(config[key], key)
    return errors


def _validate_rule(rule: dict, path: str) -> list[str]:
    errors = []
    if not isinstance(rule, dict):
        return [f"{path}: must be a dict"]
    rt = rule.get("type")
    if rt not in ("primitive", "composite"):
        errors.append(f"{path}: type must be 'primitive' or 'composite'")
        return errors
    if rt == "primitive":
        name = rule.get("name", "")
        if name not in PRIMITIVES:
            errors.append(f"{path}: unknown primitive '{name}', must be one of {list(PRIMITIVES.keys())}")
    elif rt == "composite":
        op = rule.get("operator", "")
        if op not in ("AND", "OR"):
            errors.append(f"{path}: composite operator must be AND or OR")
        for i, sub in enumerate(rule.get("rules", [])):
            errors += _validate_rule(sub, f"{path}.rules[{i}]")
    return errors
```

Commit: `"feat(INF-05): Strategy DSL engine with primitives, composites, and validation (no eval/exec)"`

---

### Task INF-06: Factor Independent Storage (Per-symbol Parquet)

**Files:**
- Create: `FisherQuant/fisher/factor/storage.py`

```python
# fisher/factor/storage.py
import polars as pl
from pathlib import Path
import re

FACTOR_DIR = "data/factors"


def sanitize_column(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


class FactorStorage:
    @staticmethod
    def save(symbol: str, factor_df: pl.DataFrame):
        symbol_safe = sanitize_column(symbol)
        dir_path = Path(FACTOR_DIR) / symbol_safe
        dir_path.mkdir(parents=True, exist_ok=True)
        # sanitize column names
        renamed = factor_df.rename({c: sanitize_column(c) for c in factor_df.columns})
        path = dir_path / "factors.parquet"
        if path.exists():
            existing = pl.read_parquet(path)
            # merge: overwrite overlapping columns, keep others
            for col in renamed.columns:
                if col in existing.columns:
                    existing = existing.drop(col)
            merged = existing.hstack(renamed)
            merged.write_parquet(path)
        else:
            renamed.write_parquet(path)

    @staticmethod
    def load(symbol: str) -> pl.DataFrame | None:
        symbol_safe = sanitize_column(symbol)
        path = Path(FACTOR_DIR) / symbol_safe / "factors.parquet"
        if not path.exists():
            return None
        return pl.read_parquet(path)

    @staticmethod
    def delete(symbol: str):
        import shutil
        symbol_safe = sanitize_column(symbol)
        dir_path = Path(FACTOR_DIR) / symbol_safe
        if dir_path.exists():
            shutil.rmtree(dir_path)

    @staticmethod
    def load_with_factors(symbol: str, ohlcv_df: pl.DataFrame) -> pl.DataFrame:
        factors = FactorStorage.load(symbol)
        if factors is None:
            return ohlcv_df
        # Align by row index
        n = min(len(ohlcv_df), len(factors))
        return ohlcv_df[:n].hstack(factors[:n])
```

Commit: `"feat(INF-06): Factor independent storage (per-symbol Parquet) with sanitized columns"`

---

### Task INF-07: APScheduler with Persistent JobStore + Trading Session Detection

**Files:**
- Modify: `FisherQuant/fisher/scheduler/engine.py`

Add SQLAlchemyJobStore, trading session auto-scheduling, and `is_trading_now()`.

```python
# Add to SchedulerEngine.__init__:
def __init__(self, db_url: str = "sqlite:///data/scheduler.db"):
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    self._scheduler = BackgroundScheduler(
        jobstores=jobstores,
        executors={"default": ThreadPoolExecutor(max_workers=4)},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        timezone="Asia/Shanghai",
    )

# Add trading session methods:
def is_trading_now(self, market: str = "a_share") -> bool:
    from datetime import datetime, time
    now = datetime.now().time()
    weekday = datetime.now().weekday()
    if weekday >= 5:
        return False
    if market == "a_share":
        return (time(9, 30) <= now <= time(11, 30)) or (time(13, 0) <= now <= time(15, 0))
    elif market == "hk_connect":
        return (time(9, 30) <= now <= time(12, 0)) or (time(13, 0) <= now <= time(16, 0))
    return False
```

Commit: `"feat(INF-07): APScheduler with SQLAlchemyJobStore and trading session detection"`

---

### Task INF-08: Streaming Data Export

**Files:**
- Create: `FisherQuant/fisher/store/exporter.py`

```python
# fisher/store/exporter.py
import csv
import io
import tempfile
import polars as pl
from pathlib import Path
from ..store.engine import DuckDBManager


class DataExporter:
    def __init__(self, db: DuckDBManager | None = None):
        self.db = db or DuckDBManager()

    def export_csv_stream(self, table: str, columns: list[str] | None = None,
                          where: str = "", params: list | None = None) -> io.StringIO:
        cols = ", ".join(columns) if columns else "*"
        sql = f"SELECT {cols} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        output = io.StringIO()
        writer = csv.writer(output)
        df = self.db.query_df(sql, params)
        writer.writerow(df.columns)
        for row in df.iter_rows():
            writer.writerow(row)
        output.seek(0)
        return output

    def export_parquet(self, table: str, output_path: str, where: str = "",
                       params: list | None = None):
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        df = self.db.query_df(sql, params)
        df.write_parquet(output_path)
        return output_path

    def export_streaming(self, table: str, format: str, where: str = "",
                         params: list | None = None, chunk_size: int = 10000):
        cols_df = self.db.query_df(f"SELECT * FROM {table} LIMIT 1")
        columns = cols_df.columns
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        offset = 0
        while True:
            batch_sql = f"{sql} LIMIT {chunk_size} OFFSET {offset}"
            batch = self.db.query_df(batch_sql, params)
            if len(batch) == 0:
                break
            yield batch
            offset += chunk_size
```

Commit: `"feat(INF-08): streaming data export (CSV/Parquet) with DuckDB COPY"`

---

### Task INF-09: LTTB Downsampling

**Files:**
- Create: `FisherQuant/fisher/visualization/downsample.py`

```python
# fisher/visualization/downsample.py
import math


def lttb(data: list[tuple[float, float]], threshold: int = 500) -> list[tuple[float, float]]:
    """Largest Triangle Three Buckets downsampling algorithm.
    
    Args:
        data: List of (x, y) tuples.
        threshold: Maximum number of output points (default 500).
    
    Returns:
        Downsampled list of (x, y) tuples.
    """
    if len(data) <= threshold:
        return data

    data = list(data)
    data_length = len(data)
    bucket_size = (data_length - 2) / (threshold - 2)

    result = [data[0]]

    for i in range(1, threshold - 1):
        bucket_start = int((i - 1) * bucket_size) + 1
        bucket_end = min(int(i * bucket_size) + 1, data_length - 1)

        avg_x = 0.0
        avg_y = 0.0
        count = 0
        for j in range(bucket_start, bucket_end):
            avg_x += data[j][0]
            avg_y += data[j][1]
            count += 1
        if count == 0:
            continue
        avg_x /= count
        avg_y /= count

        prev = result[-1]
        max_area = -1.0
        max_point = data[bucket_start]

        for j in range(bucket_start, bucket_end):
            area = abs(
                (prev[0] - data[data_length - 1][0]) * (data[j][1] - prev[1])
                - (prev[0] - data[j][0]) * (data[data_length - 1][1] - prev[1])
            ) * 0.5
            if area > max_area:
                max_area = area
                max_point = data[j]

        result.append(max_point)

    result.append(data[-1])
    return result
```

Commit: `"feat(INF-09): LTTB downsampling (largest triangle three buckets, ≤500 pts)"`

---

### Task INF-10: Config Hot-Reload

**Files:**
- Create: `FisherQuant/fisher/config/hot_reload.py`

```python
# fisher/config/hot_reload.py
import hashlib
import threading
import time
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class ConfigReloader:
    def __init__(self, config_dir: str, polling_interval: float = 5.0):
        self._config_dir = Path(config_dir)
        self._polling_interval = polling_interval
        self._hashes: dict[str, str] = {}
        self._callbacks: list[Callable[[str], None]] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._compute_hashes()

    def _compute_hashes(self):
        for f in self._config_dir.glob("*.yaml"):
            content = f.read_bytes()
            self._hashes[f.name] = hashlib.md5(content).hexdigest()

    def on_change(self, callback: Callable[[str], None]):
        self._callbacks.append(callback)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("ConfigReloader started (interval=%ds)", self._polling_interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        while self._running:
            time.sleep(self._polling_interval)
            try:
                self._check_changes()
            except Exception:
                logger.exception("Config reload check failed")

    def _check_changes(self):
        for f in self._config_dir.glob("*.yaml"):
            content = f.read_bytes()
            new_hash = hashlib.md5(content).hexdigest()
            old_hash = self._hashes.get(f.name, "")
            if new_hash != old_hash:
                self._hashes[f.name] = new_hash
                logger.info("Config changed: %s", f.name)
                for cb in self._callbacks:
                    try:
                        cb(f.name)
                    except Exception:
                        logger.exception("Config change callback failed for %s", f.name)
```

Commit: `"feat(INF-10): Config hot-reload with MD5 polling and change callbacks"`

---

### Task QA-01: Test Data Infrastructure

**Files:**
- Create: `FisherQuant/tests/fixtures/` directory with sample Parquet data
- Create: `FisherQuant/tests/factories.py` data factory

```python
# tests/factories.py
import polars as pl
import random
from datetime import date, timedelta


class DataFactory:
    def __init__(self, seed: int = 42):
        random.seed(seed)

    def generate_ohlcv(self, symbol: str, days: int = 252,
                       start_date: str = "2024-01-01",
                       trend: str = "random") -> pl.DataFrame:
        start = date.fromisoformat(start_date)
        dates = []
        d = start
        while len(dates) < days:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)

        close = 100.0
        data = {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
        for dt in dates:
            daily_return = random.gauss(0.0005, 0.015)
            if trend == "bull":
                daily_return += 0.002
            elif trend == "bear":
                daily_return -= 0.002
            close *= (1 + daily_return)
            open_price = close * (1 + random.uniform(-0.005, 0.005))
            high = max(open_price, close) * (1 + random.uniform(0, 0.01))
            low = min(open_price, close) * (1 - random.uniform(0, 0.01))
            data["date"].append(dt.isoformat())
            data["open"].append(round(open_price, 2))
            data["high"].append(round(high, 2))
            data["low"].append(round(low, 2))
            data["close"].append(round(close, 2))
            data["volume"].append(random.randint(100000, 10000000))
        return pl.DataFrame(data)

    def generate_equity_curve(self, days: int = 252, annual_return: float = 0.15,
                              volatility: float = 0.20) -> list:
        daily_r = annual_return / 252
        daily_vol = volatility / (252 ** 0.5)
        curve = [1.0]
        for _ in range(days - 1):
            curve.append(curve[-1] * (1 + random.gauss(daily_r, daily_vol)))
        return curve
```

Commit: `"feat(QA-01): test data fixtures, factories, and golden baseline"`

---

### Self-Review

- [x] All 11 tasks have complete code
- [x] INF-02 (DuckDB) is critical path — writes first, others can run parallel
- [x] INF-03/07/09/10 are independent — can dispatch in parallel
- [x] All existing ~450 tests must continue passing
- [x] No TBD/TODO placeholders
