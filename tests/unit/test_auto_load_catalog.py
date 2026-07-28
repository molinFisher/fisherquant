import akshare as ak
from datetime import datetime, timedelta

from fisher.store.engine import DuckDBManager
from fisher.store.schema import init_schema
from fisher.dash_app.services.auto_load_service import AutoLoadService
from tests.conftest import MockAKShareDF


def _make_db(tmp_path):
    # DuckDBManager 是单例，必须先清除以免复用上一测试的物理库
    DuckDBManager._instance = None
    db = DuckDBManager(str(tmp_path / "al.db"), read_pool_size=1)
    init_schema(db)
    return db


class TestRealtimeSnapshot:
    def test_upsert_and_catalog(self, tmp_path, limiter):
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        ts = datetime(2025, 3, 1, 9, 35, 0)
        svc.record_realtime_snapshot("600519.SH", "a_share", 1500.0,
                                      pre_close=1480.0, change_pct=1.35, ts=ts)
        snap = svc._db.query_df("SELECT change_pct FROM snapshots WHERE ticker='600519.SH'")
        assert snap["change_pct"][0] == 1.35
        cat = svc._db.query_df(
            "SELECT has_realtime, realtime_ts FROM cache_catalog WHERE ticker='600519.SH'")
        assert cat["has_realtime"][0] is True
        assert str(cat["realtime_ts"][0]) == "2025-03-01 09:35:00"

    def test_idempotent_upsert_no_duplicate(self, tmp_path, limiter):
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        # 同一 (ticker, ts) 重复写入应幂等替换（不新增行）
        svc.record_realtime_snapshot("600519.SH", "a_share", 1500.0, change_pct=1.0,
                                      ts=datetime(2025, 3, 1, 9, 35, 0))
        svc.record_realtime_snapshot("600519.SH", "a_share", 1510.0, change_pct=2.0,
                                      ts=datetime(2025, 3, 1, 9, 35, 0))
        n = svc._db.query_df("SELECT COUNT(*) c FROM snapshots WHERE ticker='600519.SH'")["c"][0]
        assert n == 1  # 幂等，不重复
        assert svc._db.query_df("SELECT change_pct FROM snapshots WHERE ticker='600519.SH'")["change_pct"][0] == 2.0


class TestMinuteWindow:
    def test_prune_advances_minute_start(self, tmp_path, limiter):
        """验收#9：窗口外旧分钟线惰性清理，minute_start 前移至剩余最早点。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        db.execute_many(
            "INSERT INTO bars_minute "
            "(ticker, bar_time, open, high, low, close, volume, amount, market, period) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [["600519.SH", "2024-12-15 09:31:00", 1.0, 1.0, 1.0, 1.0, 1, 1.0, "a_share", "5"],
             ["600519.SH", "2025-02-20 09:31:00", 1.0, 1.0, 1.0, 1.0, 1, 1.0, "a_share", "5"]])
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name) VALUES ('600519.SH','a_share','茅台')")
        now = datetime(2025, 3, 1, 10, 0, 0)
        deleted = svc.prune_minute_window("600519.SH", now=now, window_days=60)
        assert deleted == 1
        remaining = db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0]
        assert remaining == 1
        start = db.query_df("SELECT minute_start FROM cache_catalog WHERE ticker='600519.SH'")["minute_start"][0]
        assert str(start) == "2025-02-20 09:31:00"

    def test_fetch_and_store_minute_records_coverage(self, tmp_path, limiter, monkeypatch):
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        # 用距今天较近的时间戳，避免被窗口修剪（now-60d 之外）删除
        recent = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d 09:31:00")
        minute_rows = [{"时间": recent, "开盘": 1.0, "最高": 1.0,
                        "最低": 1.0, "收盘": 1.0, "成交量": 1, "成交额": 1.0}]

        def fake(symbol=None, period="5", start_date="", end_date=""):
            return MockAKShareDF(minute_rows)
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", fake, raising=False)

        n = svc.fetch_and_store_minute("600519.SH", "a_share", "2025-02-01", "2025-02-28", period="5")
        assert n == 1
        assert svc._db.query_df("SELECT has_minute FROM cache_catalog WHERE ticker='600519.SH'")["has_minute"][0] is True
        assert svc._db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0] == 1


class TestAutoLoadDailyCatalog:
    def test_incremental_records_daily_coverage(self, tmp_path, limiter, monkeypatch):
        """Task #6：自动加载日线写库后同事务更新 cache_catalog 覆盖度，边界不缩窄。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        db.execute(
            "INSERT INTO bars_daily "
            "(ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
            "VALUES ('600519.SH','2024-01-03',1,1,1,1,1,1,'a_share',1.0)")
        # 预置 catalog 已记录首日（模拟历史 FULL 加载）
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name, has_daily, daily_start, daily_end) "
            "VALUES ('600519.SH','a_share','茅台',TRUE, DATE '2024-01-03', DATE '2024-01-03')")

        def fake_download(ticker, market, plan, gap_start):
            # 仅补 01-04 这一天的缺口
            return [["600519.SH", "2024-01-04", 2.0, 2.0, 2.0, 2.0, 2, 2.0, "a_share", 1.0]]
        monkeypatch.setattr(svc, "_download", fake_download)

        svc.incremental_update()
        cat = db.query_df(
            "SELECT has_daily, daily_start, daily_end FROM cache_catalog WHERE ticker='600519.SH'")
        assert cat["has_daily"][0] is True
        assert str(cat["daily_start"][0]) == "2024-01-03"   # 不缩窄
        assert str(cat["daily_end"][0]) == "2024-01-04"     # 推进到新末端


class TestLoadUniverse:
    """FR-7.1 / FR-7.5：自动加载宇宙收敛为 auto_load_enabled = TRUE。"""

    def test_explicit_universe_priority(self, tmp_path, limiter):
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        svc._catalog.set_auto_load_enabled("600519.SH", True)
        svc._catalog.set_auto_load_enabled("000001.SZ", True)
        # 已有显式宇宙 → 直接返回，不走指数回退
        assert set(svc.load_universe()) == {"600519.SH", "000001.SZ"}

    def test_cold_start_falls_back_to_index(self, tmp_path, limiter, monkeypatch):
        # 库为空且无 auto_load_enabled → 回退指数成分做初始引导
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        # 指数成分 mock 已在 conftest mock_index_cons 中注册；这里确认回退非空
        universe = svc.load_universe()
        assert universe, "冷启动应回退指数成分"

    def test_existing_data_without_universe_is_empty(self, tmp_path, limiter):
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        # 模拟已通过一次性获取写入日线，但 auto_load_enabled 全 FALSE
        svc._db.execute(
            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["600519.SH", "2024-01-02", 1.0, 1.0, 1.0, 1.0, 100, 100.0, "a_share", 1.0])
        svc._catalog.set_auto_load_enabled("600519.SH", False)
        # 已有数据 + 无显式宇宙 → 收敛为空（D-4：避免整库自动加载）
        assert svc.load_universe() == []


class TestAutoLoadMinuteIncremental:
    """FR-7.2：分钟线每日盘后增量（仅 has_minute & auto_load_enabled 标的补当日）。"""

    def test_incremental_minute_tops_up_today(self, tmp_path, limiter, monkeypatch):
        """已缓存分钟线 + 纳入自动加载的标的，盘后补齐当日分钟线，has_minute 保持。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d 09:31:00")
        # 预置一只「已缓存分钟线 + 纳入自动加载」标的
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name, has_minute, auto_load_enabled) "
            "VALUES ('600519.SH','a_share','茅台',TRUE,TRUE)")
        minute_rows = [{"时间": today_str, "开盘": 1.0, "最高": 1.0,
                        "最低": 1.0, "收盘": 1.0, "成交量": 1, "成交额": 1.0}]

        def fake(symbol=None, period="5", start_date="", end_date=""):
            return MockAKShareDF(minute_rows)
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", fake, raising=False)

        res = svc.incremental_update_minute(now=today)
        assert res["processed"] == 1
        n = db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0]
        assert n == 1
        assert db.query_df(
            "SELECT has_minute FROM cache_catalog WHERE ticker='600519.SH'")["has_minute"][0] is True

    def test_incremental_minute_skips_non_minute(self, tmp_path, limiter, monkeypatch):
        """仅 has_minute=TRUE 标的纳入分钟增量宇宙（D-4 收敛，不拉全量）；空宇宙 → 不打 fetch。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        # has_minute=FALSE（仅纳入自动加载但没有分钟数据）→ 不应被分钟增量纳入
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name, has_minute, auto_load_enabled) "
            "VALUES ('600519.SH','a_share','茅台',FALSE,TRUE)")
        called = []

        def fake(symbol=None, period="5", start_date="", end_date=""):
            called.append(1)
            return MockAKShareDF([])
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", fake, raising=False)

        res = svc.incremental_update_minute(now=datetime.now())
        assert res["processed"] == 0
        assert res.get("note") == "no_minute_universe"
        assert called == []  # 空宇宙根本不应打 akshare

    def test_incremental_minute_single_failure_isolated(self, tmp_path, limiter, monkeypatch):
        """单标的 fetch 失败仅记日志，不影响其余标的（不污染 cache_catalog）。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d 09:31:00")
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name, has_minute, auto_load_enabled) "
            "VALUES ('600519.SH','a_share','茅台',TRUE,TRUE)")
        db.execute(
            "INSERT INTO cache_catalog (ticker, market, name, has_minute, auto_load_enabled) "
            "VALUES ('000001.SZ','a_share','平安',TRUE,TRUE)")

        def fake(symbol=None, period="5", start_date="", end_date=""):
            # 第一个标的成功，第二个标的抛错（模拟限频/网络）
            if symbol == "600519":
                rows = [{"时间": today_str, "开盘": 1.0, "最高": 1.0,
                         "最低": 1.0, "收盘": 1.0, "成交量": 1, "成交额": 1.0}]
                return MockAKShareDF(rows)
            raise RuntimeError("timeout")
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", fake, raising=False)

        res = svc.incremental_update_minute(now=today)
        # 成功 1 个（000001.SZ 失败被隔离），processed 仅计成功（与 incremental_update 口径一致）
        assert res["processed"] == 1
        # 成功标的写入分钟线 + 覆盖度保持
        n = db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0]
        assert n == 1
        # 失败标的无分钟线写入（未污染）
        n0 = db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='000001.SZ'")["c"][0]
        assert n0 == 0

    def test_incremental_minute_multiperiod(self, tmp_path, limiter, monkeypatch):
        """Task #25：标的已缓存 5m 与 1m 两周期，增量更新应两周期都补当日分钟线。"""
        svc = AutoLoadService(_make_db(tmp_path), limiter)
        db = svc._db
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d 09:31:00")
        db.execute(
            "INSERT INTO cache_catalog "
            "(ticker, market, name, has_minute, auto_load_enabled, minute_periods) "
            "VALUES ('600519.SH','a_share','茅台',TRUE,TRUE,'5,1')")
        fetched = []

        def fake(symbol=None, period="5", start_date="", end_date=""):
            fetched.append(period)
            rows = [{"时间": today_str, "开盘": 1.0, "最高": 1.0,
                     "最低": 1.0, "收盘": 1.0, "成交量": 1, "成交额": 1.0}]
            return MockAKShareDF(rows)
        monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", fake, raising=False)

        res = svc.incremental_update_minute(now=today)
        assert res["processed"] == 1
        # 两周期都被拉取
        assert set(fetched) == {"5", "1"}
        n = db.query_df("SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0]
        assert n == 2  # 5m 与 1m 各一根（同 bar_time 不同周期共存）
