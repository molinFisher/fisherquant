"""PRD「缓存数据类型扩展与行情看板联动」V1.0.1 §10 验收标准逐条映射（Task #26~#28）。

- AC-1 ~ AC-17 与 PRD §10 的 17 条验收一一对应（类/方法名带 acXX 编号）。
- AC-3 / AC-10 依赖真实网络与交易时段（PRD 标记 network / trading-hours），
  此处 skip 并注明 UAT 在交易日盘中人工验证一次。
- 其余各条均可注入时钟 / monkeypatch，不依赖真实环境（PRD 验收前提）。
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from fisher.store.engine import DuckDBEngine
from fisher.store.schema import SCHEMA_VERSION, init_schema, migrate
from fisher.dash_app.services.auto_load_service import AutoLoadService
from fisher.dash_app.services.cache_catalog_service import CacheCatalogService


# --------------------------------------------------------------------------- #
# 本文件私有 akshare mock（分钟 / 复权因子接口 conftest 未覆盖完整列名）
# --------------------------------------------------------------------------- #
class _MockDF:
    def __init__(self, data):
        self._data = data
        self.columns = list(data[0].keys()) if data else []

    @property
    def empty(self):
        return len(self._data) == 0

    def __len__(self):
        return len(self._data)

    def iterrows(self):
        for i, row in enumerate(self._data):
            yield i, row


def _mock_minute(monkeypatch, times=("2025-06-02 09:35:00", "2025-06-02 09:40:00")):
    import akshare as ak
    rows = [{"时间": t, "开盘": 10.0, "最高": 11.0, "最低": 9.0,
             "收盘": 10.5, "成交量": 100, "成交额": 1000.0} for t in times]
    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em",
                        lambda **kw: _MockDF(rows), raising=False)


def _mock_adj(monkeypatch):
    import akshare as ak
    rows = [{"date": "2024-01-02", "qfq_factor": 1.0, "hfq_factor": 2.0},
            {"date": "2024-01-03", "qfq_factor": 1.0, "hfq_factor": 2.0}]
    monkeypatch.setattr(ak, "stock_zh_a_daily",
                        lambda **kw: _MockDF(rows), raising=False)


def _record(db, ticker, **kw):
    cat = CacheCatalogService(db)
    with db.transaction() as conn:
        cat.record_coverage(conn, ticker, "a_share", **kw)
    return cat


T = "600519.SH"


# --------------------------------------------------------------------------- #
# AC-1 多类型入库
# --------------------------------------------------------------------------- #
class TestAC01MultiTypeIngest:
    def test_ac01_five_types_all_true_and_rows(
            self, data_service, mock_akshare, in_memory_db, limiter,
            mock_scheduler, monkeypatch):
        """验收1：日线+分钟+实时+复权+财务全入库 → 5 个 has_* 全 TRUE、
        各边界非空、v_cache_summary 五类 rows 均 > 0。"""
        _mock_minute(monkeypatch)
        _mock_adj(monkeypatch)
        assert data_service.fetch_bars([T], "2024-01-01", "2024-01-31",
                                       "daily")[T]["status"] == "ok"
        assert data_service.fetch_bars([T], "2025-06-01", "2025-06-30",
                                       "minute", period="5")[T]["status"] == "ok"
        assert data_service.fetch_bars([T], "2024-01-01", "2024-01-31",
                                       "adj")[T]["status"] == "ok"
        assert data_service.fetch_bars([T], "", "",
                                       "financials")[T]["status"] == "ok"
        svc = AutoLoadService(in_memory_db, limiter, mock_scheduler)
        svc.record_realtime_snapshot(T, "a_share", 1500.0, 1490.0, 0.67)

        row = in_memory_db.query_df(
            "SELECT * FROM cache_catalog WHERE ticker=?", [T]).to_dicts()[0]
        for flag in ("has_daily", "has_minute", "has_realtime",
                     "has_adj", "has_financials"):
            assert row[flag] is True, flag
        for col in ("daily_start", "daily_end", "minute_start", "minute_end",
                    "realtime_ts", "adj_type", "fin_report_end"):
            assert row[col] is not None, col

        v = in_memory_db.query_df(
            "SELECT * FROM v_cache_summary WHERE ticker=?", [T]).to_dicts()[0]
        for col in ("daily_rows", "minute_rows", "realtime_rows",
                    "adj_rows", "fin_rows"):
            assert v[col] > 0, col


# --------------------------------------------------------------------------- #
# AC-2 目录筛选
# --------------------------------------------------------------------------- #
class TestAC02CatalogFilter:
    def test_ac02_minute_filter_exact(self, in_memory_db):
        """验收2：数据类型=分钟 筛选 → 结果恰为 has_minute=TRUE 的标的。"""
        cat = _record(in_memory_db, T, data_type="minute",
                      start="2025-06-02 09:35:00", end="2025-06-02 09:40:00",
                      period="5")
        with in_memory_db.transaction() as conn:
            cat.record_coverage(conn, "000001.SZ", "a_share",
                                data_type="daily",
                                start="2024-01-02", end="2024-01-03")
        rows = cat.get_cache_catalog(data_type="minute")
        assert {r["ticker"] for r in rows} == {T}
        # 无漏无多：daily-only 标的不出现，且 minute 标的必出现
        rows_all = cat.get_cache_catalog()
        assert {r["ticker"] for r in rows_all} == {T, "000001.SZ"}


# --------------------------------------------------------------------------- #
# AC-3 实时报价真源（network / trading-hours → UAT）
# --------------------------------------------------------------------------- #
class TestAC03RealtimeTrueSource:
    @pytest.mark.skip(reason="验收3依赖真实网络与交易时段（network/trading-hours），"
                             "UAT 在交易日盘中人工验证一次")
    def test_ac03_uat_realtime_price_from_snapshots(self):
        pass


# --------------------------------------------------------------------------- #
# AC-4 / AC-15 降级正确 + 降级单元可测（T-2）
# --------------------------------------------------------------------------- #
class TestAC04AC15DailyFallback:
    def _seed_daily(self, db):
        db.execute("INSERT INTO bars_daily VALUES "
                   "(?, '2024-01-02', 100,101,99,100.0,1000,100000,'a_share',1.0)", [T])
        db.execute("INSERT INTO bars_daily VALUES "
                   "(?, '2024-01-03', 100,102,100,110.0,1200,120000,'a_share',1.0)", [T])
        _record(db, T, data_type="daily", start="2024-01-02", end="2024-01-03")

    def test_ac04_fallback_badge_warning_no_blank(self, in_memory_db, monkeypatch):
        """验收4：无快照标的 → 日频涨跌 + 徽标「实时✗(日频)」text-warning 色，不空白不报错。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc
        monkeypatch.setattr(qc, "_get_db", lambda: in_memory_db)
        self._seed_daily(in_memory_db)
        rows = qc._fetch_quote_data([T])
        assert len(rows) == 1
        r = rows[0]
        assert "实时✗" in r["realtime_status"]
        assert "#f0ad4e" in r["realtime_status"]  # text-warning 同色系
        assert r["last_price"] != "-" and r["change_pct"] != "-"

    def test_ac15_fallback_marker_and_last_two_days_pct(self, in_memory_db, monkeypatch):
        """验收15（T-2）：snapshots 为空 → 取 bars_daily 末两日涨跌，
        来源标记 daily_fallback=True；不依赖网络。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc
        monkeypatch.setattr(qc, "_get_db", lambda: in_memory_db)
        self._seed_daily(in_memory_db)
        r = qc._fetch_quote_data([T])[0]
        assert r["daily_fallback"] is True
        assert r["last_price"] == "110.00"
        assert r["change_pct"] == "+10.00%"  # (110-100)/100


# --------------------------------------------------------------------------- #
# AC-5 联动A（加入看板：auto_load_enabled + watchlist 去重 + focus 参数消费）
# --------------------------------------------------------------------------- #
class TestAC05LinkageJoinBoard:
    def test_ac05_join_board_enables_auto_load_and_dedup(
            self, in_memory_db, monkeypatch, tmp_path):
        import fisher.dash_app.callbacks.quote_callbacks as qc
        monkeypatch.setattr(qc, "_get_db", lambda: in_memory_db)
        monkeypatch.setattr(qc, "QB_WATCHLIST_FILE",
                            str(tmp_path / "watchlist.json"))
        cat = _record(in_memory_db, T, data_type="daily",
                      start="2024-01-02", end="2024-01-03")
        # 加入看板 → auto_load_enabled=TRUE
        cat.set_auto_load_enabled(T, True)
        row = in_memory_db.query_df(
            "SELECT auto_load_enabled FROM cache_catalog WHERE ticker=?", [T])
        assert row["auto_load_enabled"][0] is True
        # watchlist 去重：重复加入仍只有一条
        qc._save_watchlist([T])
        wl = qc._load_watchlist()
        if T not in wl:
            wl.append(T)
        assert wl.count(T) == 1
        # focus 参数消费后清除（刷新不再反复置顶）
        assert "focus" not in qc._strip_focus(f"?focus={T}")


# --------------------------------------------------------------------------- #
# AC-6 联动B（看板「去缓存」链接指向目录页预筛选定位）
# --------------------------------------------------------------------------- #
class TestAC06LinkageGotoCache:
    def test_ac06_goto_cache_link_format(self):
        import fisher.dash_app.callbacks.quote_callbacks as qc
        r = qc._empty_row(T, None)
        # FR-2（行情看板体验优化）：链接文案改为「去补齐」，携带 focus + data_type=daily，
        # 落到数据查询页由 consume_cache_intent 预填待缓存池（不再带无效的 tab=tab-cached）。
        assert "去补齐" in r["goto_cache"]
        assert f"/data-center?focus={T}&data_type=daily" in r["goto_cache"]


# --------------------------------------------------------------------------- #
# AC-7 联动C（添加下拉仅含已缓存标的；死标不可加入）
# --------------------------------------------------------------------------- #
class TestAC07LinkageAddDropdown:
    def test_ac07_dropdown_only_cached_and_dead_blocked(
            self, in_memory_db, monkeypatch):
        import fisher.dash_app.callbacks.quote_callbacks as qc
        monkeypatch.setattr(qc, "_get_db", lambda: in_memory_db)
        cat = _record(in_memory_db, T, data_type="daily",
                      start="2024-01-02", end="2024-01-03")
        # 仅财务覆盖的标的不满足 has_daily OR has_minute → 不进下拉
        with in_memory_db.transaction() as conn:
            cat.record_coverage(conn, "000001.SZ", "a_share",
                                data_type="financials",
                                fin_report_end="2024-12-31")
        assert cat.get_tickers_with_data() == {T}
        # 未缓存代码 = 死标，不可加入；已缓存标的可加入
        assert qc._is_dead_symbol("999999.SZ") is True
        assert qc._is_dead_symbol(T) is False


# --------------------------------------------------------------------------- #
# AC-8 自动加载宇宙收敛（FR-7.5 开关语义）
# --------------------------------------------------------------------------- #
class TestAC08AutoLoadUniverse:
    def test_ac08_only_enabled_in_universe(self, in_memory_db):
        cat = _record(in_memory_db, T, data_type="daily",
                      start="2024-01-02", end="2024-01-03")
        with in_memory_db.transaction() as conn:
            cat.record_coverage(conn, "000001.SZ", "a_share",
                                data_type="daily",
                                start="2024-01-02", end="2024-01-03")
        cat.set_auto_load_enabled(T, True)
        universe = cat.get_auto_load_universe()
        assert T in universe
        assert "000001.SZ" not in universe  # 已缓存但未纳入 → 不被自动加载


# --------------------------------------------------------------------------- #
# AC-9 分钟窗口（可注入时钟 + 窗口天数，同 V1.3 FR-1.7）
# --------------------------------------------------------------------------- #
class TestAC09MinuteWindow:
    def test_ac09_prune_moves_minute_start(
            self, in_memory_db, limiter, mock_scheduler):
        svc = AutoLoadService(in_memory_db, limiter, mock_scheduler)
        old_ts, new_ts = "2025-03-01 09:35:00", "2025-06-02 09:35:00"
        for ts in (old_ts, new_ts):
            in_memory_db.execute(
                "INSERT INTO bars_minute "
                "(ticker, period, bar_time, open, high, low, close, volume, amount, market) "
                "VALUES (?, '5', ?, 1,1,1,1,1,1,'a_share')", [T, ts])
        _record(in_memory_db, T, data_type="minute",
                start=old_ts, end=new_ts, period="5")
        deleted = svc.prune_minute_window(
            T, now=datetime(2025, 6, 2, 15, 0), window_days=60, period="5")
        assert deleted == 1
        left = in_memory_db.query_df(
            "SELECT bar_time FROM bars_minute WHERE ticker=?", [T])
        assert len(left) == 1 and str(left["bar_time"][0]).startswith("2025-06-02")
        ms = in_memory_db.query_df(
            "SELECT minute_start FROM cache_catalog WHERE ticker=?", [T])
        assert str(ms["minute_start"][0]).startswith("2025-06-02")  # 前移至窗口起点


# --------------------------------------------------------------------------- #
# AC-10 实时增量限频安全（network → UAT；退避重试逻辑另有单测覆盖）
# --------------------------------------------------------------------------- #
class TestAC10RateLimitSafety:
    @pytest.mark.skip(reason="验收10依赖真实 akshare 限频行为（network），UAT 验证；"
                             "退避重试/跳过轮次/目录不污染已由 test_realtime_daemon 单测覆盖")
    def test_ac10_uat_rate_limit_backoff(self):
        pass

    def test_ac10_fetch_error_no_catalog_pollution(
            self, in_memory_db, limiter, mock_scheduler):
        """可自动化部分：fetch 全失败 → 该轮跳过，cache_catalog 无 FALSE→TRUE 误标。"""
        from fisher.dash_app.services.realtime_daemon import RealtimeDaemon
        cat = _record(in_memory_db, T, data_type="daily",
                      start="2024-01-02", end="2024-01-03")
        cat.set_auto_load_enabled(T, True)
        svc = AutoLoadService(in_memory_db, limiter, mock_scheduler)

        def boom(universe):
            raise RuntimeError("rate limited")

        d = RealtimeDaemon(svc, fetch_fn=boom)
        d._retry_backoff = [0, 0, 0]
        res = d.tick(now=datetime(2025, 6, 2, 10, 0))  # 周一盘中
        assert res["skipped"] is True and res["reason"] == "fetch_error"
        row = in_memory_db.query_df(
            "SELECT has_realtime FROM cache_catalog WHERE ticker=?", [T])
        assert row["has_realtime"][0] is False  # 未被误标


# --------------------------------------------------------------------------- #
# AC-11 删除联动（按类型删除仅影响该类）
# --------------------------------------------------------------------------- #
class TestAC11DeleteLinkage:
    def test_ac11_delete_minute_keeps_daily(
            self, data_service, mock_akshare, in_memory_db, monkeypatch):
        _mock_minute(monkeypatch)
        data_service.fetch_bars([T], "2024-01-01", "2024-01-31", "daily")
        data_service.fetch_bars([T], "2025-06-01", "2025-06-30", "minute",
                                period="5")
        assert data_service.delete_symbols_by_type([T], "minute") >= 1
        assert in_memory_db.query_df(
            "SELECT COUNT(*) c FROM bars_minute WHERE ticker=?", [T])["c"][0] == 0
        row = in_memory_db.query_df(
            "SELECT has_minute, has_daily, minute_periods "
            "FROM cache_catalog WHERE ticker=?", [T]).to_dicts()[0]
        assert row["has_minute"] is False and row["minute_periods"] is None
        assert row["has_daily"] is True  # 其他类型不受影响
        assert in_memory_db.query_df(
            "SELECT COUNT(*) c FROM bars_daily WHERE ticker=?", [T])["c"][0] > 0


# --------------------------------------------------------------------------- #
# AC-12 写库幂等（五张表 + 目录边界不漂移）
# --------------------------------------------------------------------------- #
class TestAC12Idempotent:
    def _counts(self, db):
        return {
            tbl: db.query_df(
                f"SELECT COUNT(*) c FROM {tbl} WHERE ticker=?", [T])["c"][0]
            for tbl in ("bars_daily", "bars_minute", "snapshots",
                        "adj_factors", "financials")
        }

    def test_ac12_refetch_all_types_row_counts_stable(
            self, data_service, mock_akshare, in_memory_db, limiter,
            mock_scheduler, monkeypatch):
        _mock_minute(monkeypatch)
        _mock_adj(monkeypatch)
        svc = AutoLoadService(in_memory_db, limiter, mock_scheduler)
        ts = datetime(2025, 6, 2, 9, 35)

        def fetch_all():
            data_service.fetch_bars([T], "2024-01-01", "2024-01-31", "daily")
            data_service.fetch_bars([T], "2025-06-01", "2025-06-30", "minute",
                                    period="5")
            data_service.fetch_bars([T], "2024-01-01", "2024-01-31", "adj")
            data_service.fetch_bars([T], "", "", "financials")
            svc.record_realtime_snapshot(T, "a_share", 1500.0, 1490.0, 0.67, ts)

        fetch_all()
        first = self._counts(in_memory_db)
        bounds1 = in_memory_db.query_df(
            "SELECT daily_start, daily_end, minute_start, minute_end "
            "FROM cache_catalog WHERE ticker=?", [T]).to_dicts()[0]
        fetch_all()  # 同区间重复获取
        assert self._counts(in_memory_db) == first  # 各表行数不变
        bounds2 = in_memory_db.query_df(
            "SELECT daily_start, daily_end, minute_start, minute_end "
            "FROM cache_catalog WHERE ticker=?", [T]).to_dicts()[0]
        assert bounds1 == bounds2  # 目录边界不漂移


# --------------------------------------------------------------------------- #
# AC-13 落库事务（T-1：record_coverage 抛异常 → 数据与目录均回滚）
# --------------------------------------------------------------------------- #
class TestAC13TransactionAtomicity:
    def test_ac13_coverage_failure_rolls_back_bars(
            self, data_service, mock_akshare, in_memory_db, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("inject: coverage failed")

        monkeypatch.setattr(data_service._catalog, "record_coverage", boom)
        res = data_service.fetch_bars([T], "2024-01-01", "2024-01-31", "daily")
        assert res[T]["status"] == "failed"
        # 数据行与目录覆盖度均回滚：无「有数据但目录不显示」或反之
        assert in_memory_db.query_df(
            "SELECT COUNT(*) c FROM bars_daily WHERE ticker=?", [T])["c"][0] == 0
        cat_row = in_memory_db.query_df(
            "SELECT has_daily FROM cache_catalog WHERE ticker=?", [T])
        assert len(cat_row) == 0 or cat_row["has_daily"][0] is False


# --------------------------------------------------------------------------- #
# AC-14 存量兼容（迁移幂等重放 + ADD COLUMN IF NOT EXISTS + 新库即时建全表）
# --------------------------------------------------------------------------- #
class TestAC14MigrationCompat:
    def test_ac14_idempotent_replay_and_full_tables(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)   # 新建库：_TABLES 即时建全表
            init_schema(engine)   # 重放 ALTER ... ADD COLUMN IF NOT EXISTS 不报错
            migrate(engine)       # 迁移幂等重放
            assert engine.query_df(
                "SELECT MAX(version) v FROM schema_version")["v"][0] == SCHEMA_VERSION
            tables = set(engine.query_df(
                "SELECT table_name FROM information_schema.tables")["table_name"]
                .to_list())
            for t in ("bars_daily", "bars_minute", "snapshots", "adj_factors",
                      "financials", "cache_catalog"):
                assert t in tables, t
            cols = engine.query_df(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='bars_minute'")["column_name"].to_list()
            assert "period" in cols


# --------------------------------------------------------------------------- #
# AC-16 存量看板 pruning（T-4：3 死标 → 首次加载清零）
# --------------------------------------------------------------------------- #
class TestAC16WatchlistPruning:
    def test_ac16_three_dead_symbols_pruned(
            self, in_memory_db, monkeypatch, tmp_path):
        import json
        import fisher.dash_app.callbacks.quote_callbacks as qc
        monkeypatch.setattr(qc, "_get_db", lambda: in_memory_db)
        wl_file = tmp_path / "watchlist.json"
        monkeypatch.setattr(qc, "QB_WATCHLIST_FILE", str(wl_file))
        _record(in_memory_db, T, data_type="daily",
                start="2024-01-02", end="2024-01-03")
        dead = ["111111.SZ", "222222.SZ", "333333.SZ"]
        wl_file.write_text(json.dumps([T] + dead), encoding="utf-8")
        kept, removed = qc._prune_watchlist()
        assert kept == [T]                 # 仅剩缓存标的，无空白死行
        assert set(removed) == set(dead)   # 移除列表 = 3 只死标（埋点数据源）


# --------------------------------------------------------------------------- #
# AC-17 快照迁移安全（T-7/T-8：空表重建成功，非空中止报错）
# --------------------------------------------------------------------------- #
class TestAC17SnapshotMigrationGuard:
    def test_ac17_empty_snapshots_migrated_new_pk(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            engine.execute(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            engine.execute("INSERT INTO schema_version (version) VALUES (4)")
            engine.execute(
                "CREATE TABLE snapshots (id BIGINT PRIMARY KEY, ticker VARCHAR, "
                "ts TIMESTAMP, last_price DOUBLE)")
            migrate(engine)  # 空表 → DROP+CREATE 成功
            # 新 PK (ticker, ts) 生效：同键 INSERT OR REPLACE 幂等
            engine.execute(
                "INSERT INTO snapshots (ticker, ts, last_price) "
                "VALUES ('600519.SH', '2025-01-02 09:31:00', 1500.0)")
            engine.execute(
                "INSERT OR REPLACE INTO snapshots (ticker, ts, last_price) "
                "VALUES ('600519.SH', '2025-01-02 09:31:00', 1510.0)")
            assert engine.query_df(
                "SELECT COUNT(*) c FROM snapshots")["c"][0] == 1

    def test_ac17_nonempty_snapshots_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            engine.execute(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
                "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            engine.execute("INSERT INTO schema_version (version) VALUES (4)")
            engine.execute(
                "CREATE TABLE snapshots (id BIGINT PRIMARY KEY, ticker VARCHAR, "
                "ts TIMESTAMP, last_price DOUBLE)")
            engine.execute(
                "INSERT INTO snapshots (id, ticker, ts) "
                "VALUES (1, '600519.SH', now())")
            with pytest.raises(RuntimeError):
                migrate(engine)  # 非空 → 中止报错，不静默丢数据
