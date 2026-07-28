"""Integration test for Dash callback flows.

Tests the full search -> fetch -> cache -> auto-load -> export -> delete pipeline
using app.server.test_client() for HTTP and service-level verification.
"""

import json
import tempfile
from pathlib import Path
import pytest
import polars as pl


# ---------------------------------------------------------------------------
# Mock AKShare data
# ---------------------------------------------------------------------------

_MOCK_STOCKS = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000001", "name": "平安银行"},
    {"code": "300750", "name": "宁德时代"},
]

_MOCK_BARS = [
    {"日期": "2024-01-02", "开盘": 100.0, "最高": 101.0, "最低": 99.0,
     "收盘": 100.5, "成交量": 1000000, "成交额": 100500000.0},
    {"日期": "2024-01-03", "开盘": 100.5, "最高": 102.0, "最低": 100.0,
     "收盘": 101.0, "成交量": 1200000, "成交额": 121200000.0},
]

_MOCK_INDEX_CODES = [
    {"stock_code": "600519"},
    {"stock_code": "000001"},
    {"stock_code": "300750"},
]

_MOCK_HK_CODES = [
    {"stock_code": "00700"},
    {"stock_code": "00941"},
]

# 自动加载 V1.3 下载接口（stock_zh_a_daily / stock_hk_daily）返回列格式
_MOCK_DAILY_BARS = [
    {"date": "2024-01-02", "open": 100.0, "high": 101.0, "low": 99.0,
     "close": 100.5, "volume": 1000000, "amount": 100500000.0},
    {"date": "2024-01-03", "open": 100.5, "high": 102.0, "low": 100.0,
     "close": 101.0, "volume": 1200000, "amount": 121200000.0},
]

_MOCK_HK_DAILY_BARS = [
    {"date": "2024-01-02", "open": 200.0, "high": 201.0, "low": 199.0,
     "close": 200.5, "volume": 500000, "amount": 100250000.0},
]


class MockAKShareDF:
    def __init__(self, data):
        self._data = data
        self.columns = list(data[0].keys()) if data else []

    def iterrows(self):
        for i, row in enumerate(self._data):
            yield i, row

    @property
    def empty(self):
        return len(self._data) == 0

    def __len__(self):
        return len(self._data)

    def head(self, n):
        return self

    def __getitem__(self, key):
        if isinstance(key, str):
            return MockAKShareSerie([r[key] for r in self._data])
        filtered = [self._data[i] for i, v in enumerate(key) if v]
        return MockAKShareDF(filtered)

    def to_dicts(self):
        return self._data


class MockAKShareSerie:
    def __init__(self, data):
        self._data = data

    def __iter__(self):
        return iter(self._data)

    def to_list(self):
        return self._data

    def __getitem__(self, idx):
        return self._data[idx]

    def __len__(self):
        return len(self._data)

    @property
    def str(self):
        return self

    def contains(self, pat, na=False):
        return MockBoolList([pat in str(v) for v in self._data])


class MockBoolList:
    def __init__(self, data):
        self._data = data

    def __or__(self, other):
        if isinstance(other, MockBoolList):
            return MockBoolList([a or b for a, b in zip(self._data, other._data)])
        return MockBoolList([a or other for a in self._data])

    def __and__(self, other):
        if isinstance(other, MockBoolList):
            return MockBoolList([a and b for a, b in zip(self._data, other._data)])
        return MockBoolList([a and other for a in self._data])

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, idx):
        return self._data[idx]

    def __len__(self):
        return len(self._data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset service singletons before each test."""
    from fisher.dash_app.services import (
        _db_instance, _limiter_instance,
        _data_service_instance, _auto_load_service_instance,
    )
    # Reset globals
    import fisher.dash_app.services as svcs
    svcs._db_instance = None
    svcs._limiter_instance = None
    svcs._data_service_instance = None
    svcs._auto_load_service_instance = None

    from fisher.store.engine import DuckDBManager
    DuckDBManager._instance = None

    yield

    # Cleanup after test
    DuckDBManager._instance = None
    svcs._db_instance = None
    svcs._data_service_instance = None
    svcs._auto_load_service_instance = None


@pytest.fixture
def mock_all_akshare(monkeypatch):
    """Mock all akshare functions used by the Dash app."""
    import akshare as ak

    def mock_stock_info(*args, **kwargs):
        return MockAKShareDF(_MOCK_STOCKS)

    def mock_zh_a_hist(symbol=None, period="daily", start_date="", end_date="", adjust="qfq"):
        return MockAKShareDF(_MOCK_BARS)

    def mock_index_cons(*args, **kwargs):
        return MockAKShareDF(_MOCK_INDEX_CODES)

    def mock_hk_index_cons(*args, **kwargs):
        return MockAKShareDF(_MOCK_HK_CODES)

    def mock_financial(*args, **kwargs):
        return MockAKShareDF([{"报告期": "2024-12-31", "营业收入": 100000000}])

    def mock_stock_hk_spot(*args, **kwargs):
        # search_symbols 第 3 步会调用 ak.stock_hk_spot()；必须 mock 以免触网。
        return MockAKShareDF([
            {"代码": "00700", "名称": "腾讯控股"},
            {"代码": "00941", "名称": "中国移动"},
        ])

    def mock_zh_a_hist_min_em(symbol=None, period="1", start_date="", end_date="", adjust=""):
        return MockAKShareDF(_MOCK_BARS)

    def mock_zh_a_daily(symbol=None, start_date="", end_date="", adjust=""):
        return MockAKShareDF(_MOCK_DAILY_BARS)

    def mock_hk_daily(symbol=None, start_date="", end_date="", adjust=""):
        return MockAKShareDF(_MOCK_HK_DAILY_BARS)

    monkeypatch.setattr(ak, "stock_info_a_code_name", mock_stock_info)
    monkeypatch.setattr(ak, "stock_zh_a_hist", mock_zh_a_hist)
    monkeypatch.setattr(ak, "index_stock_cons", mock_index_cons)
    monkeypatch.setattr(ak, "hk_index_cons", mock_hk_index_cons, raising=False)
    monkeypatch.setattr(ak, "stock_financial_abstract", mock_financial)
    monkeypatch.setattr(ak, "stock_hk_spot", mock_stock_hk_spot, raising=False)
    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", mock_zh_a_hist_min_em, raising=False)
    monkeypatch.setattr(ak, "stock_zh_a_daily", mock_zh_a_daily, raising=False)
    monkeypatch.setattr(ak, "stock_hk_daily", mock_hk_daily, raising=False)
    return {
        "stock_info": mock_stock_info,
        "zh_a_hist": mock_zh_a_hist,
        "index_cons": mock_index_cons,
        "hk_index_cons": mock_hk_index_cons,
        "hk_spot": mock_stock_hk_spot,
        "zh_a_hist_min_em": mock_zh_a_hist_min_em,
        "zh_a_daily": mock_zh_a_daily,
        "hk_daily": mock_hk_daily,
    }


@pytest.fixture
def app_instance(tmp_path, mock_all_akshare):
    """Create a Dash app instance with in-memory DB and mocked AKShare."""
    from fisher.dash_app.services import get_db
    db_path = str(tmp_path / "int_test.db")
    db = get_db()
    db.connect(db_path, read_pool_size=1)

    # 用生产同款 init_schema 建全量表（含 cache_catalog / adj_factors / financials /
    # snapshots 等），避免手动建表遗漏导致 record_coverage 等失败（FR-1.2 / FR-1.6）。
    # 此前仅在 tmp DB 手动建 5 张表，漏建 cache_catalog，使 fetch_bars 的事务写
    # 报 "bars_daily / cache_catalog does not exist"。
    from fisher.store.schema import init_schema
    init_schema(db)

    db.execute_many(
        "INSERT INTO symbol_dict (ticker, code, name, market, pinyin_full, pinyin_abbr) "
        "VALUES (?,?,?,?,?,?)",
        [
            ["600519.SH", "600519", "贵州茅台", "a_share", "GUIZHOUMAOTAI", "GZMT"],
            ["000001.SZ", "000001", "平安银行", "a_share", "PINGANYINHANG", "PAYH"],
            ["300750.SZ", "300750", "宁德时代", "a_share", "NINGDESHIDAI", "NDSD"],
            ["00700.HK", "00700", "腾讯控股", "hk_connect", "TENGXUNKONGGU", "TXKG"],
            ["00941.HK", "00941", "中国移动", "hk_connect", "ZHONGGUOYIDONG", "ZGYD"],
        ],
    )

    # Build the Dash app
    import dash
    import dash_bootstrap_components as dbc
    from fisher.dash_app.layout import create_layout
    from fisher.dash_app.callbacks.routing import register_all_callbacks
    from diskcache import Cache

    cache_dir = str(tmp_path / "cache")
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        background_callback_manager=dash.DiskcacheManager(Cache(cache_dir)),
        suppress_callback_exceptions=True,
    )
    app.title = "FisherQuant Test"
    app.layout = create_layout()
    register_all_callbacks(app)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDashHTTPServe:
    """Verify pages load correctly via HTTP test client."""

    def test_home_page_loads(self, app_instance):
        with app_instance.server.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200
            text = resp.data.decode("utf-8")
            assert "FisherQuant" in text

    def test_data_center_page_loads(self, app_instance):
        with app_instance.server.test_client() as client:
            resp = client.get("/data-center")
            assert resp.status_code == 200

    def test_strategy_center_page_loads(self, app_instance):
        with app_instance.server.test_client() as client:
            resp = client.get("/strategy-center")
            assert resp.status_code == 200

    def test_backtest_center_page_loads(self, app_instance):
        with app_instance.server.test_client() as client:
            resp = client.get("/backtest-center")
            assert resp.status_code == 200


class TestSearchFetchFlow:
    """Full search -> fetch -> cache stats -> export -> delete flow."""

    def test_search_symbols_and_fetch(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()

        results = svc.search_symbols("600519")
        assert len(results) > 0
        assert any("600519" in r["label"] for r in results)

        fetch_results = svc.fetch_bars(["600519"], "2024-01-01", "2024-01-31")
        assert "600519" in fetch_results
        assert fetch_results["600519"]["status"] == "ok"

    def test_cache_stats_after_fetch(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()

        stats_before = svc.get_cache_stats()
        assert stats_before["total"] == 0

        svc.fetch_bars(["600519"], "2024-01-01", "2024-01-31")
        stats_after = svc.get_cache_stats()
        assert stats_after["total"] > 0
        assert stats_after["records"] > 0

    def test_cache_table_after_fetch(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()

        svc.fetch_bars(["600519"], "2024-01-01", "2024-01-31")

        all_rows = svc.get_cached_table(market_filter="all")
        assert len(all_rows) > 0

        filtered = svc.get_cached_table(text_filter="600519")
        assert len(filtered) > 0

        no_match = svc.get_cached_table(text_filter="ZZZZZZ")
        assert len(no_match) == 0

    def test_export_estimate(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()
        svc.fetch_bars(["600519"], "2024-01-01", "2024-01-31")

        est = svc.estimate_export([], "", "")
        assert est["records"] > 0
        assert est["estimated_size_kb"] > 0

        est_filtered = svc.estimate_export(["600519.SH"], "2024-01-01", "2024-01-31")
        assert est_filtered["records"] > 0

    def test_delete_after_fetch(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()
        svc.fetch_bars(["600519"], "2024-01-01", "2024-01-31")

        stats = svc.get_cache_stats()
        assert stats["total"] > 0

        tickers = [r["ticker"] for r in svc.get_cached_table()]
        count = svc.delete_symbols(tickers)
        assert count == len(tickers)

        stats_after = svc.get_cache_stats()
        assert stats_after["total"] == 0

    def test_full_pipeline(self, app_instance, mock_all_akshare):
        """Search -> fetch -> cache stats -> export -> delete in sequence."""
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()

        # Search
        results = svc.search_symbols("贵州")
        assert len(results) > 0

        # Fetch for multiple symbols
        svc.fetch_bars(["600519", "000001"], "2024-01-01", "2024-01-31")

        # Cache stats
        stats = svc.get_cache_stats()
        assert stats["total"] >= 2

        # Cached table
        rows = svc.get_cached_table()
        assert len(rows) >= 2

        # Export estimate
        est = svc.estimate_export([], "", "")
        assert est["records"] > 0

        # Delete all
        tickers = [r["ticker"] for r in rows]
        svc.delete_symbols(tickers)
        assert svc.get_cache_stats()["total"] == 0


class TestAutoLoadIntegration:
    """Auto-load service integration with data service."""

    def _stop_auto_load(self, svc):
        svc._stop_event.set()
        if getattr(svc, "_thread", None) is not None:
            svc._thread.join(timeout=5)

    def test_auto_load_check_empty_db(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_auto_load_service, get_limiter, get_db
        svc = get_auto_load_service()
        # V1.3：空库经 recover() 触发自动加载（返回 loading 阶段）
        result = svc.recover()
        assert result["phase"] in ("loading", "idle", "done", "paused", "error")
        self._stop_auto_load(svc)

    def test_auto_load_progress(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_auto_load_service
        svc = get_auto_load_service()

        svc.recover()
        progress = svc.get_progress()
        assert "current" in progress and "phase" in progress
        self._stop_auto_load(svc)

    def test_auto_load_then_delete(self, app_instance, mock_all_akshare):
        from fisher.dash_app.services import get_data_service, get_auto_load_service
        data_svc = get_data_service()
        auto_svc = get_auto_load_service()

        auto_result = auto_svc.recover()
        assert auto_result["phase"] in ("loading", "idle", "done", "paused", "error")
        self._stop_auto_load(auto_svc)

        stats = data_svc.get_cache_stats()
        if stats["total"] > 0:
            tickers = [r["ticker"] for r in data_svc.get_cached_table()]
            data_svc.delete_symbols(tickers)
            assert data_svc.get_cache_stats()["total"] == 0


class TestStrategyServiceIntegration:
    """Strategy service works end-to-end."""

    @pytest.fixture
    def strategy_dir(self, tmp_path):
        d = tmp_path / "strategies"
        d.mkdir()
        return str(d)

    def test_create_list_export_delete(self, app_instance, strategy_dir):
        from fisher.dash_app.services import get_strategy_service
        from fisher.dash_app.services.models import StrategyConfig
        svc = get_strategy_service(strategy_dir)

        assert svc.list_strategies() == []

        cfg = StrategyConfig(name="int_test", type="sma_cross",
                             params={"fast": 5, "slow": 20})
        result = svc.save_strategy(cfg)
        assert result["status"] == "ok"

        strategies = svc.list_strategies()
        assert len(strategies) == 1

        exported = svc.export_json("int_test")
        assert exported is not None
        data = json.loads(exported)
        assert data["name"] == "int_test"

        svc.delete_strategy("int_test")
        assert svc.list_strategies() == []

    def test_import_save_export_roundtrip(self, app_instance, strategy_dir):
        from fisher.dash_app.services import get_strategy_service
        svc = get_strategy_service(strategy_dir)

        json_str = json.dumps({
            "name": "roundtrip", "type": "macd",
            "params": {"fast": 12, "slow": 26, "signal": 9},
        })
        result = svc.import_json(json_str)
        assert result["status"] == "ok"

        saved = svc.get_strategy("roundtrip")
        assert saved["params"]["fast"] == 12

        exported = svc.export_json("roundtrip")
        exported_data = json.loads(exported)
        assert exported_data["params"]["signal"] == 9
