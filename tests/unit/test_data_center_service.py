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
