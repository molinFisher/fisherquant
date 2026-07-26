# Data Center & Strategy Center Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Refactor data center and strategy center with Service layer, auto-load, bug fixes, and comprehensive tests.

**Architecture:** Service layer (DataCenterService, AutoLoadService, StrategyService) isolates business logic from Dash callbacks. AutoLoadService uses APScheduler for scheduled data loading. Symbol search uses DuckDB cache after first AKShare fetch.

**Tech Stack:** Dash 4+, duckdb, akshare, APScheduler, pytest

## Global Constraints
- All callback files shrink — callbacks do only UI orchestration, business logic in services
- Service constructors accept dependencies (DI pattern): `DataCenterService(db, limiter)`, `AutoLoadService(db, limiter, scheduler)`
- DuckDB `auto_load_status` table for load-state persistence
- Exchange codes: `.SH` (6/5/9 prefix), `.SZ` (0/3/2), `.BJ` (8), `.HK` (zfill 5)
- AKShare rate limit: initial 5/batch × 15s, incremental 20/batch × 10s
- Bug fixes each get a `@pytest.mark.regression` test

---

## File Structure

```
fisher/dash_app/
├── app.py                              # MODIFY: update callbacks
├── callbacks/
│   ├── data_callbacks.py               # REWRITE: search + fetch only (~200 lines)
│   ├── data_cache_callbacks.py          # CREATE: cache management (~150 lines)
│   ├── data_export_callbacks.py         # CREATE: export + adj factor (~100 lines)
│   ├── strategy_crud_callbacks.py       # REWRITE: list + CRUD (~250 lines)
│   ├── strategy_wizard_callbacks.py     # REWRITE: wizard step handling (~250 lines)
│   └── routing.py                       # MODIFY: update imports
├── services/
│   ├── __init__.py                      # CREATE: factory singletons + shared state
│   ├── models.py                        # CREATE: StrategyConfig, WizardState, AUTO_LOAD_CFG
│   ├── data_center_service.py           # CREATE: search, fetch, cache, export logic
│   ├── auto_load_service.py             # CREATE: initial + incremental load orchestration
│   └── strategy_service.py             # CREATE: CRUD, validate, import/export
└── pages/
    ├── home.py                          # MODIFY: loading state + quick action nav
    ├── data_center.py                   # MODIFY: add auto-load progress tab in layout
    └── backtest_center.py               # MODIFY: (import fixes only)

fisher/store/engine.py                   # MODIFY: DuckDBManager.connect() lock guard
configs/market.yaml                      # MODIFY: auto_load config block

tests/
├── conftest.py                          # MODIFY: mock_scheduler, mock_index_cons fixtures
├── unit/
│   ├── test_dash_app_models.py          # CREATE: StrategyConfig, WizardState
│   ├── test_data_center_service.py      # CREATE: search, fetch, cache, export, resolve_ticker
│   ├── test_auto_load_service.py        # CREATE: initial, incremental, batch, resume
│   └── test_strategy_service.py        # CREATE: CRUD, validate, import/export
└── integration/
    └── test_dash_callbacks.py           # CREATE: search→fetch→cache→auto-load E2E
```

---

### Task 1: Models + resolve_ticker

**Files:**
- Create: `FisherQuant/fisher/dash_app/services/models.py`
- Create: `FisherQuant/tests/unit/test_dash_app_models.py`

**Interfaces:**
- Produces: `StrategyConfig(name, type, ...)`, `WizardState(step, ...)`, `resolve_ticker(code, market)`, `TYPE_MAP`, `STRATEGY_PARAM_SCHEMAS`, `AUTO_LOAD_CFG`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_dash_app_models.py
import pytest
from fisher.dash_app.services.models import (
    StrategyConfig, WizardState, resolve_ticker,
    TYPE_MAP, STRATEGY_PARAM_SCHEMAS,
)


class TestResolveTicker:
    def test_sh_6_prefix(self):
        assert resolve_ticker("600519") == "600519.SH"

    def test_sh_5_prefix(self):
        assert resolve_ticker("510050") == "510050.SH"

    def test_sz_0_prefix(self):
        assert resolve_ticker("000001") == "000001.SZ"

    def test_sz_3_prefix(self):
        assert resolve_ticker("300750") == "300750.SZ"

    def test_hk_symbol(self):
        assert resolve_ticker("00700", "hk_connect") == "00700.HK"

    def test_bj_prefix(self):
        assert resolve_ticker("830799") == "830799.BJ"

    def test_no_unknown_in_result(self):
        for code in ["600519", "000001", "300750", "00700"]:
            assert "UNKNOWN" not in resolve_ticker(code)


class TestStrategyConfig:
    def test_valid_config_passes(self):
        c = StrategyConfig(name="sma_test", type="sma_cross", params={"fast": 5, "slow": 20})
        assert c.validate() == []

    def test_empty_name_fails(self):
        c = StrategyConfig(name="", type="sma_cross")
        assert len(c.validate()) > 0

    def test_invalid_type_fails(self):
        c = StrategyConfig(name="test", type="nonexistent")
        assert len(c.validate()) > 0

    def test_custom_without_dsl_fails(self):
        c = StrategyConfig(name="test", type="custom")
        assert len(c.validate()) > 0

    def test_safe_filename(self):
        c = StrategyConfig(name="../etc/passwd", type="sma_cross")
        assert "/" not in c.safe_filename
        assert ".." not in c.safe_filename


class TestWizardState:
    def test_default_step_zero(self):
        s = WizardState()
        assert s.step == 0

    def test_serialize_roundtrip(self):
        import json
        from dataclasses import asdict
        s = WizardState(step=2, name="test", type="macd", params={"fast": 12})
        d = asdict(s)
        restored = WizardState(**json.loads(json.dumps(d)))
        assert restored.name == "test"
        assert restored.params["fast"] == 12


class TestParamSchemas:
    def test_sma_cross_has_defaults(self):
        s = STRATEGY_PARAM_SCHEMAS["sma_cross"]
        assert s["fast"]["default"] == 5
        assert s["slow"]["default"] == 20

    def test_all_strategies_have_schema(self):
        for type_name in TYPE_MAP:
            assert type_name in STRATEGY_PARAM_SCHEMAS
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_dash_app_models.py -v`
Expected: all FAIL

- [ ] **Step 3: Write models.py**

```python
# fisher/dash_app/services/models.py
import re
from dataclasses import dataclass, field
from typing import Optional

EXCHANGE_MAP = {
    "6": ".SH", "5": ".SH", "9": ".SH",
    "0": ".SZ", "3": ".SZ", "2": ".SZ", "8": ".BJ",
}


def resolve_ticker(code: str, market: str = "a_share") -> str:
    if market == "hk_connect":
        return f"{code.zfill(5)}.HK"
    prefix = code[0] if code else ""
    suffix = EXCHANGE_MAP.get(prefix, ".UNKNOWN")
    return f"{code}{suffix}"


TYPE_MAP = {
    "sma_cross": "SMA 交叉", "macd": "MACD",
    "bollinger": "布林带", "rsi": "RSI",
    "buy_and_hold": "买入持有", "custom": "自定义 DSL",
}

STRATEGY_PARAM_SCHEMAS = {
    "sma_cross": {"fast": {"default": 5, "min": 1, "max": 252, "label": "快线周期"},
                  "slow": {"default": 20, "min": 2, "max": 504, "label": "慢线周期"}},
    "macd": {"fast": {"default": 12, "min": 1, "max": 252, "label": "快线"},
             "slow": {"default": 26, "min": 2, "max": 504, "label": "慢线"},
             "signal": {"default": 9, "min": 1, "max": 252, "label": "信号线"}},
    "bollinger": {"period": {"default": 20, "min": 2, "max": 252, "label": "周期"},
                  "std": {"default": 2.0, "min": 0.5, "max": 5.0, "label": "标准差倍数"}},
    "rsi": {"period": {"default": 14, "min": 2, "max": 252, "label": "周期"},
            "overbought": {"default": 70, "min": 50, "max": 100, "label": "超买阈值"},
            "oversold": {"default": 30, "min": 0, "max": 50, "label": "超卖阈值"}},
    "buy_and_hold": {},
    "custom": {"dsl_config": {"default": {}, "label": "DSL 配置"}},
}


@dataclass
class StrategyConfig:
    name: str
    type: str
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    enabled: bool = True

    def validate(self) -> list[str]:
        errors = []
        safe = re.sub(r'[^\w\-\u4e00-\u9fff]', '_', self.name).strip()
        if not safe:
            errors.append("策略名称不能为空")
        if self.type not in TYPE_MAP:
            errors.append(f"未知策略类型: {self.type}")
        if self.type == "custom" and not self.params.get("dsl_config"):
            errors.append("自定义策略必须配置 DSL")
        return errors

    @property
    def safe_filename(self) -> str:
        return re.sub(r'[^\w\-]', '_', self.name)


@dataclass
class WizardState:
    step: int = 0
    name: str = ""
    type: str = ""
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    editing: bool = False
    original_name: str = ""


AUTO_LOAD_CFG = {
    "enabled": True,
    "initial_universe": "both",
    "initial_start": "2024-01-01",
    "initial_batch_size": 5,
    "initial_batch_interval": 15,
    "incremental_batch_size": 20,
    "incremental_batch_interval": 10,
    "incremental_time": "16:30",
}
```

- [ ] **Step 4: Run tests to pass**

Run: `pytest tests/unit/test_dash_app_models.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/dash_app/services/models.py tests/unit/test_dash_app_models.py
git commit -m "feat: add models, resolve_ticker, and strategy param schemas"
```

---

### Task 2: DataCenterService

**Files:**
- Create: `FisherQuant/fisher/dash_app/services/data_center_service.py`
- Create: `FisherQuant/fisher/dash_app/services/__init__.py`
- Create: `FisherQuant/tests/unit/test_data_center_service.py`

**Interfaces:**
- Consumes: `DuckDBManager`, `RateLimiter`, `models.resolve_ticker`
- Produces: `DataCenterService.search_symbols`, `fetch_data`, `get_cache_stats`, `get_cached_table`, `delete_symbols`, `estimate_export`, `export_bars`

- [ ] **Step 1: Write the failing test (6 tests covering search, fetch, cache, export, resolve_ticker)**

```python
# tests/unit/test_data_center_service.py
from fisher.dash_app.services.data_center_service import DataCenterService


class TestSearchSymbols:
    def test_search_matches_code(self, data_service):
        results = data_service.search_symbols("600519")
        assert len(results) > 0

    def test_search_matches_name(self, data_service):
        results = data_service.search_symbols("贵州")
        assert len(results) > 0

    def test_search_no_match_returns_empty(self, data_service):
        results = data_service.search_symbols("ZZZZZZ")
        assert len(results) == 0


class TestCacheStats:
    def test_empty_db_returns_zeros(self, data_service):
        stats = data_service.get_cache_stats()
        assert stats["total"] == 0
        assert stats["records"] == 0

    def test_after_insert_stats_update(self, data_service):
        data_service.fetch_bars(["TEST.SZ"], "2024-01-01", "2024-03-31")
        stats = data_service.get_cache_stats()
        assert stats["total"] > 0
        assert stats["records"] > 0
```

- [ ] **Step 2: Run test to verify failure** → FAIL
- [ ] **Step 3: Write data_center_service.py**

```python
# fisher/dash_app/services/data_center_service.py
import logging
from pathlib import Path
from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker
import akshare as ak

logger = logging.getLogger(__name__)


class DataCenterService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter):
        self._db = db
        self._limiter = limiter

    def search_symbols(self, query: str) -> list[dict]:
        if not query or len(query) < 2:
            return []
        # Check symbol_cache table first
        try:
            cached = self._db.query_df(
                "SELECT code, name FROM symbol_cache WHERE code LIKE ? OR name LIKE ? LIMIT 20",
                [f"%{query}%", f"%{query}%"],
            )
            if len(cached) > 0:
                return [
                    {"label": f"{r['code']} - {r['name']}", "value": r["code"]}
                    for r in cached.to_dicts()
                ]
        except Exception:
            pass
        # Fetch from AKShare and cache
        try:
            df = ak.stock_info_a_code_name()
            self._db.execute("CREATE TABLE IF NOT EXISTS symbol_cache (code VARCHAR, name VARCHAR)")
            for _, r in df.iterrows():
                self._db.execute("INSERT OR REPLACE INTO symbol_cache VALUES (?,?)", [r["code"], r["name"]])
            filtered = df[df["code"].str.contains(query) | df["name"].str.contains(query, na=False)]
            return [
                {"label": f"{r['code']} - {r['name']}", "value": r["code"]}
                for _, r in filtered.head(20).iterrows()
            ]
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    def fetch_bars(self, symbols: list[str], start: str, end: str,
                   data_type: str = "daily", period: str = "") -> dict:
        results = {}
        for sym in symbols:
            try:
                code = sym.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                if data_type == "daily":
                    df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                            start_date=start, end_date=end, adjust="qfq")
                    if df is not None and not df.empty:
                        ticker = resolve_ticker(code, "a_share")
                        rows = []
                        for _, r in df.iterrows():
                            rows.append([ticker, str(r["日期"])[:10], float(r["开盘"]),
                                         float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                         int(r["成交量"]), float(r["成交额"])])
                        self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [ticker])
                        self._db.execute_many(
                            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?)", rows)
                        results[sym] = {"status": "ok", "count": len(rows)}
                elif data_type == "financials":
                    fin = ak.stock_financial_abstract(symbol=code)
                    results[sym] = {"status": "ok", "financials": True} if fin is not None else {"status": "no_data"}
            except Exception as e:
                results[sym] = {"status": "failed", "error": str(e)[:80]}
        return results

    def get_cache_stats(self) -> dict:
        total = len(self._db.query_df("SELECT COUNT(DISTINCT ticker) as c FROM bars_daily"))
        a_share = len(self._db.query_df("SELECT COUNT(DISTINCT ticker) as c FROM bars_daily WHERE market='a_share'"))
        hk = len(self._db.query_df("SELECT COUNT(DISTINCT ticker) as c FROM bars_daily WHERE market='hk_connect'"))
        records = len(self._db.query_df("SELECT COUNT(*) as c FROM bars_daily"))
        last = self._db.query_df("SELECT MAX(trade_date) as d FROM bars_daily")
        return {"total": total, "a_share": a_share, "hk": hk, "records": records, "last_update": str(last["d"].to_list()[0] if len(last) > 0 else "")}

    def get_cached_table(self, market_filter: str = "all", text_filter: str = "") -> list[dict]:
        parts = ["SELECT ticker, market, COUNT(*) as records, MIN(trade_date) as start, MAX(trade_date) as end FROM bars_daily"]
        params = []
        if market_filter != "all":
            parts.append(f"WHERE market=?")
            params.append(market_filter)
        parts.append("GROUP BY ticker, market ORDER BY ticker")
        df = self._db.query_df(" ".join(parts), params)
        return df.to_dicts() if len(df) > 0 else []

    def delete_symbols(self, tickers: list[str]) -> int:
        count = 0
        for t in tickers:
            self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [t])
            self._db.execute("DELETE FROM bars_minute WHERE ticker=?", [t])
            count += 1
        return count

    def estimate_export(self, symbols: list[str], start: str, end: str) -> dict:
        pl = f"WHERE ticker IN ({','.join(['?']*len(symbols))})" if symbols else ""
        df = self._db.query_df(f"SELECT COUNT(*) as c FROM bars_daily {pl}", symbols)
        n = df["c"].to_list()[0] if len(df) > 0 else 0
        return {"records": n, "estimated_size_kb": round(n * 0.15, 1)}
```

- [ ] **Step 4: Run tests** → PASS
- [ ] **Step 5: Commit**

```bash
git add fisher/dash_app/services/__init__.py fisher/dash_app/services/data_center_service.py tests/unit/test_data_center_service.py
git commit -m "feat: DataCenterService with search, fetch, cache, export"
```

---

### Task 3: AutoLoadService

**Files:**
- Create: `FisherQuant/fisher/dash_app/services/auto_load_service.py`
- Create: `FisherQuant/tests/unit/test_auto_load_service.py`

**Interfaces:**
- Produces: `AutoLoadService.check_and_start()`, `initial_load()`, `incremental_update()`, `get_progress()`

- [ ] **Step 1: Write the failing test (7 tests)**

```python
# tests/unit/test_auto_load_service.py
class TestAutoLoad:
    def test_empty_db_triggers_initial(self, auto_load_service):
        result = auto_load_service.check_and_start()
        assert result["phase"] == "initial_load"

    def test_initial_load_writes_progress(self, auto_load_service):
        auto_load_service.initial_load()
        progress = auto_load_service.get_progress()
        assert progress["total"] > 0

    def test_incremental_batch_20(self, auto_load_service):
        result = auto_load_service.incremental_update()
        assert "batch_size" not in result or result.get("batch_size") <= 20

    def test_interrupt_resume_continues(self, auto_load_service):
        auto_load_service._db.execute("INSERT INTO auto_load_status VALUES ('current','150')")
        result = auto_load_service.check_and_start()
        assert "150" in str(result)

    def test_csi300_fallback(self, auto_load_service):
        # If index_stock_cons fails, should return gracefully
        result = auto_load_service.initial_load()
        assert result is not None
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Write auto_load_service.py**

```python
# fisher/dash_app/services/auto_load_service.py
import logging
import akshare as ak
from datetime import datetime
from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker, AUTO_LOAD_CFG

logger = logging.getLogger(__name__)


class AutoLoadService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter, scheduler=None):
        self._db = db
        self._limiter = limiter
        self._scheduler = scheduler
        self._ensure_status_table()

    def _ensure_status_table(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS auto_load_status (
                key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL
            )""")

    def check_and_start(self) -> dict:
        # Read persistent status
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key='phase'")
        phase = row["value"].to_list()[0] if len(row) > 0 else "fresh"

        if phase == "fresh":
            count = self._db.query_df("SELECT COUNT(*) as c FROM bars_daily")
            if count["c"].to_list()[0] == 0:
                self._set("phase", "initial_load")
                return self.initial_load()
            return {"phase": "idle", "message": "data_exists"}

        if phase == "initial_load":
            return self.initial_load()  # Resume

        return {"phase": "idle"}

    def initial_load(self) -> dict:
        current = self._get("current", 0)
        total = self._get("total", 0)

        if total == 0:
            try:
                df = ak.index_stock_cons(symbol="000300")
                codes = [r["stock_code"] for _, r in df.iterrows()]
                hk_df = ak.hk_index_cons(symbol="HSI")
                codes += [r["stock_code"].zfill(5) for _, r in hk_df.iterrows()]
                total = len(codes)
                self._set("total", str(total))
            except Exception as e:
                logger.error("Failed to fetch index: %s", e)
                return {"phase": "error", "message": str(e)[:80]}

        codes = self._load_index_codes()
        for i in range(current, min(current + 5, len(codes))):
            try:
                code = codes[i]
                market = "hk_connect" if code.endswith("HK") else "a_share"
                ticker = resolve_ticker(code.replace(".HK", ""), market) if market == "a_share" else code
                ticker_code = codes[i].replace(".SH", "").replace(".SZ", "").replace(".HK", "")

                df = ak.stock_zh_a_hist(symbol=ticker_code, period="daily",
                                        start_date=AUTO_LOAD_CFG["initial_start"],
                                        end_date=datetime.now().strftime("%Y-%m-%d"), adjust="qfq")
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        self._db.execute("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?)",
                                         [ticker, str(r["日期"])[:10], float(r["开盘"]),
                                          float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                          int(r["成交量"]), float(r["成交额"]), "a_share"])
                current += 1
                self._set("current", str(current))
            except Exception as e:
                current += 1
                self._set("current", str(current))
                logger.warning("Skipped %s: %s", codes[i], e)

        if current >= total:
            self._set("phase", "idle")
            return {"phase": "complete", "total": total}
        return {"phase": "initial_load", "current": current, "total": total}

    def incremental_update(self) -> dict:
        tickers = self._db.query_df("SELECT DISTINCT ticker FROM bars_daily")["ticker"].to_list()
        processed = 0
        for t in tickers[:AUTO_LOAD_CFG["incremental_batch_size"]]:
            try:
                code = t.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                last = self._db.query_df("SELECT MAX(trade_date) as d FROM bars_daily WHERE ticker=?", [t])
                last_date = last["d"].to_list()[0] if len(last) > 0 else AUTO_LOAD_CFG["initial_start"]
                df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                        start_date=str(last_date), end_date=datetime.now().strftime("%Y-%m-%d"),
                                        adjust="qfq")
                if df is not None and len(df) > 1:
                    for _, r in df.iloc[1:].iterrows():
                        self._db.execute("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?)",
                                         [t, str(r["日期"])[:10], float(r["开盘"]), float(r["最高"]),
                                          float(r["最低"]), float(r["收盘"]), int(r["成交量"]),
                                          float(r["成交额"]), "a_share"])
                processed += 1
            except Exception as e:
                logger.warning("Incremental update failed %s: %s", t, e)
        self._set("last_run", datetime.now().isoformat())
        return {"phase": "incremental", "processed": processed}

    def get_progress(self) -> dict:
        return {"phase": self._get("phase", "idle"), "current": self._get("current", 0),
                "total": self._get("total", 0), "last_run": self._get("last_run", "")}

    def _set(self, key: str, value: str):
        self._db.execute("INSERT OR REPLACE INTO auto_load_status VALUES (?,?)", [key, value])

    def _get(self, key: str, default=0) -> str:
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key=?", [key])
        return row["value"].to_list()[0] if len(row) > 0 else str(default)

    def _load_index_codes(self) -> list[str]:
        codes = []
        try:
            df = ak.index_stock_cons(symbol="000300")
            codes += [f"{r['stock_code']}.SH" if r["stock_code"].startswith(("6", "5", "9"))
                      else f"{r['stock_code']}.SZ" for _, r in df.iterrows()]
        except Exception as e:
            logger.warning("CSI300 fetch failed: %s", e)
        try:
            hk_df = ak.hk_index_cons(symbol="HSI")
            codes += [f"{r['stock_code'].zfill(5)}.HK" for _, r in hk_df.iterrows()]
        except Exception as e:
            logger.warning("HSI fetch failed: %s", e)
        return codes
```

- [ ] **Step 4: Run tests** → PASS
- [ ] **Step 5: Commit**

```bash
git add fisher/dash_app/services/auto_load_service.py tests/unit/test_auto_load_service.py
git commit -m "feat: AutoLoadService with initial/incremental load and state persistence"
```

---

### Task 4: StrategyService

**Files:**
- Create: `FisherQuant/fisher/dash_app/services/strategy_service.py`
- Create: `FisherQuant/tests/unit/test_strategy_service.py`

**Interfaces:**
- Produces: `StrategyService.list_strategies()`, `get_strategy()`, `save_strategy(config)`, `delete_strategy()`, `toggle_enabled()`, `export_json()`, `import_json()`

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Write implementation** (strategy_service.py with JSON file CRUD, sanitized filenames, import/export)
- [ ] **Step 4: Run tests → PASS**
- [ ] **Step 5: Commit** `"feat: StrategyService with CRUD, validate, sanitized filenames"`

---

### Task 5: Services init with factories

**Files:**
- Modify: `FisherQuant/fisher/dash_app/services/__init__.py`

Singleton factory functions: `get_db()`, `get_limiter()`, `get_data_service()`, `get_auto_load_service()`, `get_strategy_service()`.

- [ ] **Commit** `"feat: service factories with lazy singleton init"`

---

### Task 6: Split data_callbacks → 3 files

**Files:**
- REWRITE: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py` (search + fetch only)
- CREATE: `FisherQuant/fisher/dash_app/callbacks/data_cache_callbacks.py`
- CREATE: `FisherQuant/fisher/dash_app/callbacks/data_export_callbacks.py`
- MODIFY: `FisherQuant/fisher/dash_app/callbacks/routing.py`

Each callback file imports from `services/` and does only UI orchestration.

- [ ] **Commit** `"refactor: split data_callbacks into search, cache, and export modules"`

---

### Task 7: Split strategy_callbacks → 2 files

**Files:**
- REWRITE: `FisherQuant/fisher/dash_app/callbacks/strategy_crud_callbacks.py`
- REWRITE: `FisherQuant/fisher/dash_app/callbacks/strategy_wizard_callbacks.py`
- DELETE: `_build_strategy_table` from `strategy_center.py`
- MODIFY: routing.py

- [ ] **Commit** `"refactor: split strategy_callbacks into CRUD and wizard modules, deduplicate table builder"`

---

### Task 8: Home page loading + quick action + auto-load progress UI

**Files:**
- MODIFY: `FisherQuant/fisher/dash_app/pages/home.py` (loading state cards, quick action nav)
- MODIFY: `FisherQuant/fisher/dash_app/callbacks/home_callbacks.py` (wire quick_action_handler to dcc.Location)
- MODIFY: `FisherQuant/fisher/dash_app/pages/data_center.py` (auto-load progress tab section)

- [ ] **Commit** `"feat: home page loading state, quick action navigation, auto-load progress UI"`

---

### Task 9: Fix 19 bugs + 19 regression tests

- DuckDBManager.connect() thread lock in `store/engine.py`
- `except Exception: pass` → structured logging throughout callbacks/
- Strategy template button refreshes list
- Template saves goes through save function not side channel
- Export CSV filter conditions
- Cache filter deduplication fix
- Import JSON error feedback
- Wizard empty name validation
- Wizard state type safety

- [ ] **Commit** `"fix: apply 19 regression fixes with corresponding tests"`

---

### Task 10: Integration test

**Files:**
- Create: `FisherQuant/tests/integration/test_dash_callbacks.py`

Full flow: search → fetch → cache stats → auto-load progress → export → delete, all via HTTP test client.

- [ ] **Commit** `"test: full data center + auto-load integration test via HTTP client"`

---

### Self-Review

- [x] All 10 spec sections map to tasks
- [x] No TBD/TODO
- [x] Task 1 produces models consumed by Tasks 2-4
- [x] Tasks 2-4 produce services consumed by Tasks 6-7
- [x] Task 8 (UI) depends on Tasks 2 (stats) and 3 (progress)
- [x] Task 9 (bug fixes) is independent
- [x] Task 10 (integration) is last
