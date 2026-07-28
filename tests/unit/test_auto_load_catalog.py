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
