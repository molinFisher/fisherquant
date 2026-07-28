import pandas as pd
import pytest
from fisher.dash_app.services.data_center_service import DataCenterService
from fisher.dash_app.services.models import resolve_ticker


class TestSearchSymbols:
    """V1.2 新搜索：只读 symbol_dict，不触发实时 akshare。"""

    def test_search_matches_code(self, seeded_dict_service):
        results = seeded_dict_service.search_symbols("600519")
        assert len(results) > 0
        assert results[0]["value"] == "600519.SH"
        assert results[0]["code"] == "600519"
        assert results[0]["name"] == "贵州茅台"

    def test_search_matches_name(self, seeded_dict_service):
        results = seeded_dict_service.search_symbols("贵州")
        assert any(r["name"] == "贵州茅台" for r in results)

    def test_search_matches_pinyin_abbr(self, seeded_dict_service):
        results = seeded_dict_service.search_symbols("GZMT")
        assert any(r["value"] == "600519.SH" for r in results)

    def test_search_matches_pinyin_full(self, seeded_dict_service):
        results = seeded_dict_service.search_symbols("guizhou")
        assert any(r["value"] == "600519.SH" for r in results)

    def test_search_hk_zero_pad_variant(self, seeded_dict_service):
        # 输入 '700' 应命中港股 00700.HK（零填充变体）并优先靠前
        results = seeded_dict_service.search_symbols("700")
        assert any(r["value"] == "00700.HK" for r in results)

    def test_search_result_carries_market(self, seeded_dict_service):
        results = seeded_dict_service.search_symbols("00700")
        hit = next(r for r in results if r["value"] == "00700.HK")
        assert hit["market"] == "hk_connect"

    def test_search_no_match_returns_empty(self, seeded_dict_service):
        assert seeded_dict_service.search_symbols("ZZZZZZ") == []

    def test_search_does_not_call_akshare(self, seeded_dict_service, monkeypatch):
        # 新链路绝不触网：把 akshare 关键接口设为抛错，搜索仍应正常
        import akshare as ak

        def boom(*a, **k):
            raise AssertionError("search must not call akshare")

        monkeypatch.setattr(ak, "stock_info_a_code_name", boom, raising=False)
        monkeypatch.setattr(ak, "stock_hk_spot", boom, raising=False)
        monkeypatch.setattr(ak, "stock_hk_ggt_components_em", boom, raising=False)
        results = seeded_dict_service.search_symbols("600519")
        assert len(results) > 0

    def test_search_short_query_returns_empty(self, seeded_dict_service):
        assert seeded_dict_service.search_symbols("A") == []

    def test_search_empty_query_returns_empty(self, seeded_dict_service):
        assert seeded_dict_service.search_symbols("") == []

    def test_search_none_query_returns_empty(self, seeded_dict_service):
        assert seeded_dict_service.search_symbols(None) == []

    def test_legacy_switch_falls_back(self, in_memory_db, limiter, mock_akshare):
        # legacy=True 时回退旧链路（实时 akshare mock），返回 label 含代码
        svc = DataCenterService(in_memory_db, limiter)
        svc._legacy_search = True
        results = svc.search_symbols("600519")
        assert any("600519" in r["label"] for r in results)


class TestRefreshSymbolDict:
    """R-11/R-12：字典刷新 + 原子替换。"""

    @pytest.fixture
    def mock_dict_sources(self, monkeypatch):
        import akshare as ak

        def mock_a(*a, **k):
            return pd.DataFrame({"code": ["600519", "000001"],
                                 "name": ["贵州茅台", "平安银行"]})

        def mock_hk(*a, **k):
            return pd.DataFrame({"代码": ["00700", "09988"],
                                 "中文名称": ["腾讯控股", "阿里巴巴-W"]})

        monkeypatch.setattr(ak, "stock_info_a_code_name", mock_a, raising=False)
        monkeypatch.setattr(ak, "stock_hk_spot", mock_hk, raising=False)

    def test_refresh_populates_dict(self, data_service, mock_dict_sources):
        stats = data_service.refresh_symbol_dict()
        assert stats["replaced"] is True
        assert stats["a_share"] == 2
        assert stats["hk_connect"] == 2
        assert stats["total"] == 4
        df = data_service._db.query_df("SELECT ticker, name, pinyin_abbr FROM symbol_dict ORDER BY ticker")
        tickers = df["ticker"].to_list()
        assert "600519.SH" in tickers
        assert "00700.HK" in tickers

    def test_refresh_is_atomic_replace(self, data_service, mock_dict_sources):
        # 先灌入一条脏数据，刷新后应被整体替换
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market) VALUES "
            "('STALE.SH','999999','旧数据','a_share')"
        )
        data_service.refresh_symbol_dict()
        df = data_service._db.query_df("SELECT COUNT(*) AS c FROM symbol_dict WHERE ticker='STALE.SH'")
        assert df["c"][0] == 0

    def test_refresh_generates_pinyin(self, data_service, mock_dict_sources):
        data_service.refresh_symbol_dict()
        df = data_service._db.query_df(
            "SELECT pinyin_abbr FROM symbol_dict WHERE ticker='600519.SH'")
        assert df["pinyin_abbr"][0] == "GZMT"

    def test_refresh_empty_sources_keeps_old(self, data_service, monkeypatch):
        import akshare as ak
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market) VALUES "
            "('KEEP.SH','600000','浦发银行','a_share')"
        )

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(ak, "stock_info_a_code_name", boom, raising=False)
        monkeypatch.setattr(ak, "stock_hk_spot", boom, raising=False)
        stats = data_service.refresh_symbol_dict()
        assert stats["replaced"] is False
        df = data_service._db.query_df("SELECT COUNT(*) AS c FROM symbol_dict")
        assert df["c"][0] == 1  # 旧数据保留


class TestFetchBars:
    def test_fetch_daily_ok(self, data_service, mock_akshare):
        results = data_service.fetch_bars(["600519"], "2024-01-01", "2024-01-31")
        assert "600519" in results
        assert results["600519"]["status"] == "ok"
        assert results["600519"]["count"] > 0

    def test_fetch_multiple_symbols(self, data_service, mock_akshare):
        results = data_service.fetch_bars(["600519", "000001"], "2024-01-01", "2024-01-31")
        assert len(results) == 2

    def test_fetch_empty_list(self, data_service):
        results = data_service.fetch_bars([], "2024-01-01", "2024-01-31")
        assert results == {}

    def test_fetch_financials(self, data_service, mock_akshare):
        results = data_service.fetch_bars(["600519"], "2024-01-01", "2024-01-31",
                                          data_type="financials")
        assert "600519" in results

    def test_fetch_stores_in_db(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519"], "2024-01-01", "2024-01-31")
        df = data_service._db.query_df("SELECT COUNT(*) as c FROM bars_daily")
        assert df["c"][0] > 0

    def test_fetch_daily_converts_date_to_compact(self, data_service, monkeypatch):
        """回归（2026-07-28）：stock_zh_a_hist 只接受 YYYYMMDD，
        传 ISO 带横线日期会被东财断连 → 空结果 →「无数据」。"""
        import akshare as ak
        captured = {}

        def fake_hist(symbol=None, period="daily", start_date="", end_date="", adjust=""):
            captured["start"] = start_date
            captured["end"] = end_date
            return None

        monkeypatch.setattr(ak, "stock_zh_a_hist", fake_hist)
        data_service.fetch_bars(["600519.SH"], "2026-07-01", "2026-07-25")
        assert captured["start"] == "20260701"
        assert captured["end"] == "20260725"

    def test_fetch_daily_hk_routes_to_hk_daily(self, data_service, monkeypatch):
        """回归（2026-07-28）：港股日线走 stock_hk_daily 并按区间过滤，
        原实现对 .HK 也调 A 股接口必失败。"""
        import akshare as ak
        rows = [
            {"date": "2023-12-29", "open": 1.0, "high": 1.0, "low": 1.0,
             "close": 1.0, "volume": 10},   # 区间外，应被过滤
            {"date": "2024-01-02", "open": 2.0, "high": 2.0, "low": 2.0,
             "close": 2.0, "volume": 20},
        ]

        def fake_hk_daily(symbol=None, **kwargs):
            assert symbol == "00700"
            return pd.DataFrame(rows)

        monkeypatch.setattr(ak, "stock_hk_daily", fake_hk_daily, raising=False)
        results = data_service.fetch_bars(["00700.HK"], "2024-01-01", "2024-01-31")
        assert results["00700.HK"]["status"] == "ok"
        assert results["00700.HK"]["count"] == 1
        df = data_service._db.query_df(
            "SELECT market FROM bars_daily WHERE ticker='00700.HK'")
        assert df["market"][0] == "hk_connect"

    def test_fetch_daily_empty_reports_reason(self, data_service, monkeypatch):
        """回归（2026-07-28）：空结果需明确写入失败原因，不再静默丢失。"""
        import akshare as ak
        monkeypatch.setattr(ak, "stock_zh_a_hist", lambda *a, **k: None)
        results = data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        assert results["600519.SH"]["status"] == "failed"
        assert "无数据" in results["600519.SH"]["error"]

    def test_fetch_daily_records_catalog_coverage(self, data_service, mock_akshare):
        """FR-1.6：日线写库成功后 cache_catalog.has_daily=TRUE 且边界正确。"""
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        df = data_service._db.query_df(
            "SELECT has_daily, daily_start, daily_end FROM cache_catalog WHERE ticker='600519.SH'")
        assert len(df) == 1
        assert df["has_daily"][0] is True
        assert str(df["daily_start"][0]) == "2024-01-02"
        assert str(df["daily_end"][0]) == "2024-01-03"

    def test_fetch_minute_records_catalog_coverage(self, data_service, monkeypatch):
        """FR-1.6：分钟线写库成功后 cache_catalog.has_minute=TRUE。"""
        import akshare as ak
        minute_bars = [
            {"时间": "2024-01-02 09:31:00", "开盘": 100.0, "最高": 101.0,
             "最低": 99.0, "收盘": 100.5, "成交量": 1000, "成交额": 100500.0},
            {"时间": "2024-01-02 09:32:00", "开盘": 100.5, "最高": 102.0,
             "最低": 100.0, "收盘": 101.0, "成交量": 1200, "成交额": 121200.0},
        ]

        def mock_min_em(symbol=None, period="1", start_date="", end_date="", adjust=""):
            from tests.conftest import MockAKShareDF
            return MockAKShareDF(minute_bars)
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", mock_min_em, raising=False)

        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31", data_type="minute")
        df = data_service._db.query_df(
            "SELECT has_minute FROM cache_catalog WHERE ticker='600519.SH'")
        assert df["has_minute"][0] is True

    def test_fetch_idempotent_boundary_no_shrink(self, data_service, mock_akshare):
        """验收 12：重复获取同区间，bars_daily 行数与 catalog 边界均不漂移。"""
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        n1 = data_service._db.query_df("SELECT COUNT(*) c FROM bars_daily WHERE ticker='600519.SH'")["c"][0]
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        n2 = data_service._db.query_df("SELECT COUNT(*) c FROM bars_daily WHERE ticker='600519.SH'")["c"][0]
        assert n1 == n2
        df = data_service._db.query_df("SELECT daily_start, daily_end FROM cache_catalog WHERE ticker='600519.SH'")
        assert str(df["daily_start"][0]) == "2024-01-02"
        assert str(df["daily_end"][0]) == "2024-01-03"

    def test_fetch_failure_rolls_back_catalog(self, data_service, mock_akshare, monkeypatch):
        """验收 13：写库与 catalog 覆盖度同事务，数据写库抛异常则 catalog 也回滚。"""
        # 正常返回数据，但在事务提交前制造异常：让 record_coverage 抛错。
        original_record = data_service._catalog.record_coverage

        def boom(*a, **k):
            raise RuntimeError("simulated catalog failure")
        data_service._catalog.record_coverage = boom
        try:
            res = data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        finally:
            data_service._catalog.record_coverage = original_record
        assert res["600519.SH"]["status"] == "failed"
        # 数据行应回滚（事务整体回滚）
        n = data_service._db.query_df("SELECT COUNT(*) c FROM bars_daily WHERE ticker='600519.SH'")["c"][0]
        assert n == 0
        # catalog 也无该行
        nc = data_service._db.query_df("SELECT COUNT(*) c FROM cache_catalog WHERE ticker='600519.SH'")["c"][0]
        assert nc == 0


class TestCacheStats:
    def test_empty_db_returns_zeros(self, data_service):
        stats = data_service.get_cache_stats()
        assert stats["total"] == 0
        assert stats["records"] == 0

    def test_after_insert_stats_update(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        stats = data_service.get_cache_stats()
        assert stats["total"] > 0
        assert stats["records"] > 0

    def test_stats_has_all_keys(self, data_service):
        stats = data_service.get_cache_stats()
        for key in ["total", "a_share", "hk", "records", "last_update"]:
            assert key in stats


class TestGetCachedTable:
    def test_empty_db(self, data_service):
        result = data_service.get_cached_table()
        assert result == []

    def test_after_fetch(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.get_cached_table()
        assert len(result) > 0

    def test_filter_by_market(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.get_cached_table(market_filter="a_share")
        assert len(result) > 0

        result_hk = data_service.get_cached_table(market_filter="hk_connect")
        assert len(result_hk) == 0

    def test_cached_table_has_name_column(self, data_service, mock_akshare):
        # R-33：缓存表通过 LEFT JOIN symbol_dict 带出名称
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market) VALUES "
            "('600519.SH','600519','贵州茅台','a_share')"
        )
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.get_cached_table()
        row = next(r for r in result if r["ticker"] == "600519.SH")
        assert "name" in row
        assert row["name"] == "贵州茅台"

    def test_cached_table_filter_by_name(self, data_service, mock_akshare):
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market) VALUES "
            "('600519.SH','600519','贵州茅台','a_share')"
        )
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.get_cached_table(text_filter="茅台")
        assert any(r["ticker"] == "600519.SH" for r in result)


class TestDeleteSymbols:
    def test_delete_existing(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        count = data_service.delete_symbols(["600519.SH"])
        assert count == 1
        stats = data_service.get_cache_stats()
        assert stats["total"] == 0

    def test_delete_nonexistent(self, data_service):
        count = data_service.delete_symbols(["NONEXIST"])
        assert count == 1

    def test_delete_empty_list(self, data_service):
        count = data_service.delete_symbols([])
        assert count == 0


class TestEstimateExport:
    def test_zero_records(self, data_service):
        result = data_service.estimate_export([], "", "")
        assert result["records"] == 0

    def test_after_fetch(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export([], "", "")
        assert result["records"] > 0
        assert result["estimated_size_kb"] > 0

    def test_with_symbol_filter(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export(["600519.SH"], "", "")
        assert result["records"] > 0

    def test_with_date_range(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        result = data_service.estimate_export([], "2024-01-01", "2024-01-31")
        assert result["records"] > 0


class TestResolveTickerIntegration:
    def test_resolve_via_service(self):
        assert resolve_ticker("600519") == "600519.SH"
        assert resolve_ticker("000001") == "000001.SZ"
        assert resolve_ticker("00700", "hk_connect") == "00700.HK"


class TestDeleteByType:
    """FR-1.5 / 验收 11：按类型删除仅删该类数据并联动 has_*；整行删除清目录行。"""

    def _seed(self, data_service, mock_akshare):
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31")
        data_service.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31",
                                data_type="minute", period="5")

    def test_delete_minute_only(self, data_service, mock_akshare):
        self._seed(data_service, mock_akshare)
        n = data_service.delete_symbols_by_type(["600519.SH"], "minute")
        assert n == 1
        db = data_service._db
        assert db.query_df(
            "SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'"
        ).to_dicts()[0]["c"] == 0
        # 日线不受影响
        assert db.query_df(
            "SELECT COUNT(*) c FROM bars_daily WHERE ticker='600519.SH'"
        ).to_dicts()[0]["c"] > 0
        cat = db.query_df(
            "SELECT has_daily, has_minute, minute_start, minute_end "
            "FROM cache_catalog WHERE ticker='600519.SH'"
        ).to_dicts()[0]
        assert cat["has_daily"] is True
        assert cat["has_minute"] is False
        assert cat["minute_start"] is None and cat["minute_end"] is None

    def test_delete_full_row_clears_catalog(self, data_service, mock_akshare):
        self._seed(data_service, mock_akshare)
        n = data_service.delete_symbols(["600519.SH"])
        assert n == 1
        db = data_service._db
        for table in ("bars_daily", "bars_minute", "cache_catalog"):
            assert db.query_df(
                f"SELECT COUNT(*) c FROM {table} WHERE ticker='600519.SH'"
            ).to_dicts()[0]["c"] == 0

    def test_delete_unknown_type_noop(self, data_service, mock_akshare):
        self._seed(data_service, mock_akshare)
        assert data_service.delete_symbols_by_type(["600519.SH"], "nope") == 0
        assert data_service._db.query_df(
            "SELECT COUNT(*) c FROM bars_daily WHERE ticker='600519.SH'"
        ).to_dicts()[0]["c"] > 0
