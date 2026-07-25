import pytest
from fisher.dash_app.services.data_center_service import DataCenterService
from fisher.dash_app.services.models import resolve_ticker


class TestSearchSymbols:
    def test_search_matches_code(self, data_service, mock_akshare):
        results = data_service.search_symbols("600519")
        assert len(results) > 0
        assert any("600519" in r["label"] for r in results)

    def test_search_matches_name(self, data_service, mock_akshare):
        results = data_service.search_symbols("贵州")
        assert len(results) > 0
        assert any("贵州" in r["label"] for r in results)

    def test_search_no_match_returns_empty(self, data_service, mock_akshare):
        results = data_service.search_symbols("ZZZZZZ")
        assert len(results) == 0

    def test_search_short_query_returns_empty(self, data_service):
        results = data_service.search_symbols("A")
        assert len(results) == 0

    def test_search_empty_query_returns_empty(self, data_service):
        results = data_service.search_symbols("")
        assert len(results) == 0

    def test_search_none_query_returns_empty(self, data_service):
        results = data_service.search_symbols(None)
        assert len(results) == 0


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
