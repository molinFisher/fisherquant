import tempfile
from pathlib import Path

from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.dash_app.services.cache_catalog_service import CacheCatalogService


def _make(tmp_path):
    engine = DuckDBEngine(str(tmp_path / "test.db"))
    init_schema(engine)
    # 预置 symbol_dict 名称，验证 name 兜底
    engine.execute(
        "INSERT INTO symbol_dict (ticker, code, name, market) VALUES (?,?,?,?)",
        ["600519.SH", "600519", "贵州茅台", "a_share"],
    )
    return engine


class TestRecordCoverage:
    def test_records_daily_coverage_in_transaction(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(
                conn, "600519.SH", "a_share", data_type="daily",
                start="2024-01-01", end="2025-01-01",
            )
        row = engine.query_df("SELECT * FROM cache_catalog WHERE ticker='600519.SH'").to_dicts()[0]
        assert row["has_daily"] is True
        assert str(row["daily_start"]) == "2024-01-01"
        assert str(row["daily_end"]) == "2025-01-01"
        # name 应从 symbol_dict 兜底
        assert row["name"] == "贵州茅台"

    def test_boundary_merge_idempotent(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily",
                                 start="2024-01-01", end="2025-01-01")
        # 重复获取更窄区间，边界不缩窄（验收 12）
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily",
                                 start="2024-06-01", end="2024-12-01")
        row = engine.query_df("SELECT daily_start, daily_end FROM cache_catalog WHERE ticker='600519.SH'").to_dicts()[0]
        assert str(row["daily_start"]) == "2024-01-01"
        assert str(row["daily_end"]) == "2025-01-01"

    def test_rollback_keeps_catalog_consistent(self, tmp_path):
        """验收 13：数据写库与 catalog 覆盖度在同一事务，抛异常则均回滚。"""
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        try:
            with engine.transaction() as conn:
                conn.execute(
                    "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ["600519.SH", "2024-01-02", 1.0, 1.0, 1.0, 1.0, 100, 100.0, "a_share", 1.0],
                )
                svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily",
                                    start="2024-01-02", end="2024-01-02")
                raise RuntimeError("simulated write failure")
        except RuntimeError:
            pass
        # 数据行应回滚
        n_bars = engine.query_df("SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='600519.SH'")["c"][0]
        assert n_bars == 0
        # catalog 覆盖度也应回滚（无该行）
        n_cat = engine.query_df("SELECT COUNT(*) AS c FROM cache_catalog WHERE ticker='600519.SH'")["c"][0]
        assert n_cat == 0

    def test_clear_coverage_on_delete(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="minute",
                                 start="2024-01-01", end="2024-02-01")
        with engine.transaction() as conn:
            svc.clear_coverage(conn, "600519.SH", "minute")
        has = engine.query_df("SELECT has_minute FROM cache_catalog WHERE ticker='600519.SH'")["has_minute"][0]
        assert has is False


class TestGetCacheCatalog:
    def test_filter_by_type(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily")
            svc.record_coverage(conn, "000001.SZ", "a_share", data_type="minute")
        daily = svc.get_cache_catalog(data_type="daily")
        tickers = {r["ticker"] for r in daily}
        assert tickers == {"600519.SH"}
        minute = svc.get_cache_catalog(data_type="minute")
        assert {r["ticker"] for r in minute} == {"000001.SZ"}

    def test_filter_by_market_and_text(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily")
            svc.record_coverage(conn, "00700.HK", "hk_connect", data_type="daily")
        hk = svc.get_cache_catalog(market="hk_connect")
        assert {r["ticker"] for r in hk} == {"00700.HK"}
        txt = svc.get_cache_catalog(text="茅台")
        assert {r["ticker"] for r in txt} == {"600519.SH"}


class TestAutoLoadUniverse:
    def test_set_and_get_universe(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        svc.set_auto_load_enabled("600519.SH", True)
        svc.set_auto_load_enabled("000001.SZ", True)
        universe = set(svc.get_auto_load_universe())
        assert universe == {"600519.SH", "000001.SZ"}
        svc.set_auto_load_enabled("000001.SZ", False)
        assert set(svc.get_auto_load_universe()) == {"600519.SH"}


class TestCacheSummary:
    """FR-8.2：v_cache_summary 目录页数据源 + 多类型 AND 筛选。"""

    def test_summary_counts_and_type_filter(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            conn.execute(
                "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
                ["600519.SH", "2024-01-02", 1.0, 1.0, 1.0, 1.0, 100, 100.0, "a_share", 1.0],
            )
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily",
                                start="2024-01-02", end="2024-01-02")
            svc.record_coverage(conn, "00700.HK", "hk_connect", data_type="minute",
                                start="2024-01-02 09:30:00", end="2024-01-02 15:00:00")
        rows = svc.get_cache_summary()
        assert len(rows) == 2
        maotai = next(r for r in rows if r["ticker"] == "600519.SH")
        assert maotai["daily_rows"] == 1 and maotai["minute_rows"] == 0
        # 多类型 AND 语义：没有标的同时具备 daily+minute
        assert svc.get_cache_summary(data_types=["daily", "minute"]) == []
        only_daily = svc.get_cache_summary(data_types=["daily"])
        assert [r["ticker"] for r in only_daily] == ["600519.SH"]
        # 市场 + 文本筛选
        assert [r["ticker"] for r in svc.get_cache_summary(market="hk_connect")] == ["00700.HK"]
        assert [r["ticker"] for r in svc.get_cache_summary(text="茅台")] == ["600519.SH"]


class TestBackfill:
    """v5 存量回填：老库 bars_daily 有数据但 catalog 为空时，init_schema 自动回填。"""

    def test_backfill_from_existing_bars(self, tmp_path):
        engine = _make(tmp_path)
        # 模拟存量：直接写 bars 不经 record_coverage，然后清空 catalog
        engine.execute(
            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["600519.SH", "2024-01-02", 1.0, 1.0, 1.0, 1.0, 100, 100.0, "a_share", 1.0],
        )
        engine.execute(
            "INSERT INTO bars_minute (ticker, bar_time, open, high, low, close, volume, amount, market, period) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["600519.SH", "2024-01-02 09:35:00", 1.0, 1.0, 1.0, 1.0, 10, 10.0, "a_share", "5"],
        )
        engine.execute("DELETE FROM cache_catalog")
        init_schema(engine)  # 触发回填
        row = engine.query_df(
            "SELECT * FROM cache_catalog WHERE ticker='600519.SH'"
        ).to_dicts()[0]
        assert row["has_daily"] is True and row["has_minute"] is True
        assert str(row["daily_start"]) == "2024-01-02"
        assert row["name"] == "贵州茅台"  # 名称从 symbol_dict 兜底

    def test_backfill_skips_when_catalog_populated(self, tmp_path):
        engine = _make(tmp_path)
        svc = CacheCatalogService(engine)
        with engine.transaction() as conn:
            svc.record_coverage(conn, "600519.SH", "a_share", data_type="daily",
                                start="2024-01-02", end="2024-01-02")
        engine.execute(
            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["000001.SZ", "2024-01-02", 1.0, 1.0, 1.0, 1.0, 100, 100.0, "a_share", 1.0],
        )
        init_schema(engine)  # catalog 非空 → 不回填
        assert len(engine.query_df(
            "SELECT * FROM cache_catalog"
        ).to_dicts()) == 1
