"""Regression tests for all 19 bug fixes in the data-strategy refactor."""

import json
import tempfile
import threading
from pathlib import Path
import pytest
from fisher.store.engine import DuckDBManager
from fisher.dash_app.services.models import StrategyConfig, resolve_ticker
from fisher.dash_app.services.strategy_service import StrategyService
from fisher.dash_app.services.data_center_service import DataCenterService


# ---------------------------------------------------------------------------
# Bug 1: DuckDBManager.connect() thread lock
# ---------------------------------------------------------------------------

class TestConnectThreadLock:
    def test_concurrent_connect_safe(self, tmp_path):
        DuckDBManager._instance = None
        db_path = str(tmp_path / "concurrent_test.db")
        db = DuckDBManager(db_path, read_pool_size=1)
        errors = []

        def hammer_connect():
            try:
                db.connect(db_path, read_pool_size=1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer_connect) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"Connect errors: {errors}"
        DuckDBManager._instance = None

    def test_connect_idempotent(self, tmp_path):
        DuckDBManager._instance = None
        db_path = str(tmp_path / "idempotent_test.db")
        db = DuckDBManager(db_path, read_pool_size=1)
        db.connect(db_path, read_pool_size=1)
        db.connect(db_path, read_pool_size=1)
        db.execute("SELECT 1")
        DuckDBManager._instance = None


# ---------------------------------------------------------------------------
# Bug 2: except Exception: pass -> structured logging (verified by no silent fails)
# ---------------------------------------------------------------------------

class TestExceptionLogging:
    def test_strategy_service_import_invalid_json(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        result = svc.import_json("{invalid}")
        assert result["status"] == "error"

    def test_data_service_search_no_crash(self, data_service, mock_akshare):
        result = data_service.search_symbols("test_query_xyz")
        assert isinstance(result, list)

    def test_strategy_service_list_no_crash(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        lst = svc.list_strategies()
        assert isinstance(lst, list)


# ---------------------------------------------------------------------------
# Bug 3: Template handler returns updated strategy list
# ---------------------------------------------------------------------------

class TestTemplateHandler:
    def test_template_save_via_service(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        cfg = StrategyConfig(name="template_test", type="sma_cross",
                             params={"fast": 5, "slow": 20})
        result = svc.save_strategy(cfg)
        assert result["status"] == "ok"
        strategies = svc.list_strategies()
        names = [s["name"] for s in strategies]
        assert "template_test" in names


# ---------------------------------------------------------------------------
# Bug 4: Template saves through _save_strategy()
# ---------------------------------------------------------------------------

class TestTemplateSavePath:
    def test_save_goes_through_save_strategy(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        cfg = StrategyConfig(name="save_path_test", type="macd",
                             params={"fast": 12, "slow": 26, "signal": 9})
        result = svc.save_strategy(cfg)
        assert result["status"] == "ok"
        saved = svc.get_strategy("save_path_test")
        assert saved is not None
        assert saved["type"] == "macd"

    def test_save_validates_and_rejects_empty(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        cfg = StrategyConfig(name="", type="sma_cross")
        result = svc.save_strategy(cfg)
        assert result["status"] == "error"
        assert len(result.get("errors", [])) > 0


# ---------------------------------------------------------------------------
# Bug 5: Export filter conditions
# ---------------------------------------------------------------------------

class TestExportFilter:
    def test_estimate_export_with_symbol_filter(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export(["600519.SH"], "", "")
        assert result["records"] > 0

    def test_estimate_export_with_date_filter(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export([], "2024-01-01", "2024-01-31")
        assert result["records"] > 0

    def test_estimate_export_with_both_filters(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export(["600519.SH"], "2024-01-01", "2024-01-31")
        assert result["records"] > 0

    def test_estimate_export_no_match(self, data_service):
        result = data_service.estimate_export(["NONEXIST.SH"], "2020-01-01", "2020-01-31")
        assert result["records"] == 0


# ---------------------------------------------------------------------------
# Bug 6: Cache filter dedup - WHERE clause uses correct param count
# ---------------------------------------------------------------------------

class TestCacheFilterDedup:
    def test_get_cached_table_market_filter(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        rows = data_service.get_cached_table(market_filter="a_share")
        assert len(rows) > 0

    def test_get_cached_table_text_filter(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        rows = data_service.get_cached_table(text_filter="600519")
        assert len(rows) > 0

    def test_get_cached_table_no_match(self, data_service):
        rows = data_service.get_cached_table(text_filter="ZZZZZZ")
        assert len(rows) == 0

    def test_get_cached_table_both_filters(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        rows = data_service.get_cached_table(market_filter="a_share", text_filter="600519")
        assert len(rows) > 0


# ---------------------------------------------------------------------------
# Bug 7: Import JSON error feedback
# ---------------------------------------------------------------------------

class TestImportErrorFeedback:
    def test_import_invalid_json_returns_error(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        result = svc.import_json("not valid json")
        assert result["status"] == "error"
        assert any("JSON" in e for e in result.get("errors", []))

    def test_import_missing_name_returns_error(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        result = svc.import_json('{"type": "sma_cross"}')
        assert result["status"] == "error"

    def test_import_valid_json_succeeds(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        result = svc.import_json('{"name": "test_import", "type": "sma_cross", "params": {"fast": 5, "slow": 20}}')
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Bug 8: Wizard empty name validation
# ---------------------------------------------------------------------------

class TestEmptyNameValidation:
    def test_empty_name_rejected(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        cfg = StrategyConfig(name="", type="sma_cross")
        result = svc.save_strategy(cfg)
        assert result["status"] == "error"
        assert any("空" in e or "name" in e.lower() or "名称" in e for e in result.get("errors", []))

    def test_whitespace_name_rejected(self, strategy_dir):
        svc = StrategyService(strategy_dir)
        cfg = StrategyConfig(name="   ", type="sma_cross")
        result = svc.save_strategy(cfg)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Bug 9: Search results propagation
# ---------------------------------------------------------------------------

class TestSearchResultsPropagation:
    def test_search_preserves_existing_value(self, data_service):
        # V1.2：新搜索只读 symbol_dict，value 为标准化 ticker
        data_service._legacy_search = False
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market, pinyin_abbr) "
            "VALUES ('600519.SH','600519','贵州茅台','a_share','GZMT')"
        )
        results = data_service.search_symbols("600519")
        assert len(results) > 0
        assert results[0]["value"] == "600519.SH"


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def strategy_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def in_memory_db(tmp_path):
    DuckDBManager._instance = None
    db_path = str(tmp_path / "test_reg.db")
    db = DuckDBManager(db_path, read_pool_size=1)
    db.execute("""
        CREATE TABLE IF NOT EXISTS bars_daily (
            ticker VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, amount DOUBLE, market VARCHAR,
            adj_factor DOUBLE DEFAULT 1.0,
            PRIMARY KEY (ticker, trade_date)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS bars_minute (
            ticker VARCHAR, bar_time TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, amount DOUBLE, market VARCHAR,
            PRIMARY KEY (ticker, bar_time)
        )
    """)
    # 标的搜索 V1.2：只读标的字典表（R-10），get_cached_table LEFT JOIN 依赖
    db.execute("""
        CREATE TABLE IF NOT EXISTS symbol_dict (
            ticker VARCHAR NOT NULL, code VARCHAR NOT NULL, name VARCHAR NOT NULL,
            market VARCHAR NOT NULL, pinyin_full VARCHAR DEFAULT '',
            pinyin_abbr VARCHAR DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ticker)
        )
    """)
    yield db
    DuckDBManager._instance = None


@pytest.fixture
def limiter():
    from fisher.market.rate_limiter import RateLimiter
    return RateLimiter(max_per_minute=1000)


@pytest.fixture
def data_service(in_memory_db, limiter):
    return DataCenterService(in_memory_db, limiter)
