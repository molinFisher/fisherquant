"""实时守护线程单测（PRD FR-7.6 / D-5，Task #16）。

验证：
- 交易时段门控（is_trading_hours）；
- 非交易时段 / 空宇宙 → tick 跳过且绝不打 fetch；
- 交易时段 → 经注入 fetch_fn 取快照，调用 record_realtime_snapshot 写入
  snapshots + 同事务更新 cache_catalog.realtime_ts（验收 15 同源降级逻辑的前置）。
不依赖真实网络。
"""

import pytest

from fisher.store.engine import DuckDBManager
from fisher.store.schema import init_schema
from fisher.dash_app.services.cache_catalog_service import CacheCatalogService
from fisher.dash_app.services.realtime_daemon import (
    RealtimeDaemon, is_trading_hours,
)


def _make(tmp_path):
    DuckDBManager._instance = None
    db = DuckDBManager(str(tmp_path / "rt.db"), read_pool_size=1)
    init_schema(db)
    return db


class FakeCatalog:
    def __init__(self, universe):
        self._universe = universe
        self.get_auto_load_universe_called = 0

    def get_auto_load_universe(self):
        self.get_auto_load_universe_called += 1
        return list(self._universe)


class FakeAutoLoad:
    """最小 AutoLoadService 替身，仅实现 record_realtime_snapshot 写入路径。"""

    def __init__(self, db, catalog):
        self._db = db
        self._catalog = catalog
        self.written = []

    def record_realtime_snapshot(self, ticker, market, last, pre, pct, ts):
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snapshots "
                "(ticker, ts, last_price, pre_close, market, change_pct) "
                "VALUES (?,?,?,?,?,?)", [ticker, ts, last, pre, market, pct])
            self._catalog.record_coverage(
                conn, ticker, market, data_type="realtime", realtime_ts=ts)
        self.written.append(ticker)


def test_is_trading_hours():
    from datetime import datetime
    # 周三 10:00 → 盘中
    assert is_trading_hours(datetime(2024, 1, 3, 10, 0, 0)) is True
    # 周六 → 休市
    assert is_trading_hours(datetime(2024, 1, 6, 10, 0, 0)) is False
    # 午休 12:30 → 休市
    assert is_trading_hours(datetime(2024, 1, 3, 12, 30, 0)) is False
    # 收盘后 16:00 → 休市
    assert is_trading_hours(datetime(2024, 1, 3, 16, 0, 0)) is False


def test_tick_non_trading_skips_fetch(tmp_path):
    db = _make(tmp_path)
    catalog = FakeCatalog(["600519.SH"])
    svc = FakeAutoLoad(db, catalog)
    fetched = []

    def fake_fetch(universe):
        fetched.append(universe)
        return {}

    daemon = RealtimeDaemon(svc, interval=60, fetch_fn=fake_fetch, catalog=catalog)
    from datetime import datetime
    res = daemon.tick(now=datetime(2024, 1, 6, 10, 0, 0))  # 周六
    assert res == {"skipped": True, "reason": "non_trading"}
    assert fetched == []  # 非交易时段绝不打 fetch（限频保护）
    assert svc.written == []


def test_tick_writes_snapshots(tmp_path):
    db = _make(tmp_path)
    real_catalog = CacheCatalogService(db)  # 真实目录服务（供 record_coverage 写入）
    catalog = FakeCatalog(["600519.SH"])    # 仅用于 daemon 取宇宙
    svc = FakeAutoLoad(db, real_catalog)

    def fake_fetch(universe):
        # 返回 ticker -> (last, pre, pct, vol)
        return {"600519.SH": (11.0, 10.0, 1.5, 500)}

    daemon = RealtimeDaemon(svc, interval=60, fetch_fn=fake_fetch, catalog=catalog)
    from datetime import datetime
    res = daemon.tick(now=datetime(2024, 1, 3, 10, 0, 0))  # 周三盘中
    assert res["skipped"] is False
    assert res["written"] == 1
    assert svc.written == ["600519.SH"]
    # 同事务：catalog.realtime_ts 已更新
    row = db.query_df(
        "SELECT realtime_ts FROM cache_catalog WHERE ticker='600519.SH'"
    ).to_dicts()[0]
    assert row["realtime_ts"] is not None
    snap = db.query_df(
        "SELECT last_price, change_pct FROM snapshots WHERE ticker='600519.SH'"
    ).to_dicts()[0]
    assert snap["last_price"] == 11.0 and snap["change_pct"] == 1.5


def test_tick_empty_universe_skips(tmp_path):
    db = _make(tmp_path)
    catalog = FakeCatalog([])  # 空宇宙
    svc = FakeAutoLoad(db, catalog)

    def fake_fetch(universe):
        raise AssertionError("不应调用 fetch")

    daemon = RealtimeDaemon(svc, interval=60, fetch_fn=fake_fetch, catalog=catalog)
    from datetime import datetime
    res = daemon.tick(now=datetime(2024, 1, 3, 10, 0, 0))
    assert res == {"skipped": True, "reason": "empty_universe"}


def test_tick_rate_limit_retries_then_skips(tmp_path):
    """FR-7.4 / 验收 10：模拟 akshare 限频 → 退避重试后跳过该轮，
    cache_catalog 不被污染（无 FALSE→TRUE 误标），且不影响后续轮次。"""
    db = _make(tmp_path)
    real_catalog = CacheCatalogService(db)   # 真实目录服务（供 record_coverage 写入）
    catalog = FakeCatalog(["600519.SH"])     # 仅用于 daemon 取宇宙
    svc = FakeAutoLoad(db, real_catalog)
    attempts = {"n": 0}

    def flaky_fetch(universe):
        attempts["n"] += 1
        raise RuntimeError("akshare 限频 429")  # 限频/超时

    daemon = RealtimeDaemon(svc, interval=60, fetch_fn=flaky_fetch, catalog=catalog)
    daemon._retry_max_attempts = 3
    daemon._retry_backoff = [0, 0, 0]  # 退避为 0，CI 加速
    from datetime import datetime
    res = daemon.tick(now=datetime(2024, 1, 3, 10, 0, 0))  # 盘中
    # 退避重试 3 次仍失败 → 跳过该轮
    assert res["reason"] == "fetch_error"
    assert attempts["n"] == 3
    # cache_catalog 不被污染：该轮根本未写快照（无 FALSE→TRUE 误标）
    assert svc.written == []
    # 该轮失败不影响后续轮次：换正常 fetch_fn，下一轮仍能正常写入（主流程不被阻塞）
    def good_fetch(universe):
        return {"600519.SH": (11.0, 10.0, 1.0, 500)}
    daemon._fetch_fn = good_fetch
    res2 = daemon.tick(now=datetime(2024, 1, 3, 10, 0, 0))
    assert res2["skipped"] is False
    assert res2["written"] == 1
    assert svc.written == ["600519.SH"]


def test_tick_rate_limit_interrupted_during_backoff(tmp_path):
    """FR-7.4：退避期间收到停止信号 → 立即放弃本轮，不空转等待。"""
    db = _make(tmp_path)
    catalog = FakeCatalog(["600519.SH"])
    svc = FakeAutoLoad(db, catalog)
    attempts = {"n": 0}

    def flaky_fetch(universe):
        attempts["n"] += 1
        raise RuntimeError("timeout")

    daemon = RealtimeDaemon(svc, interval=60, fetch_fn=flaky_fetch, catalog=catalog)
    daemon._retry_max_attempts = 3
    daemon._retry_backoff = [30, 30, 30]  # 长退避
    daemon._stop.set()  # 模拟暂停/停止信号已置位
    from datetime import datetime
    res = daemon.tick(now=datetime(2024, 1, 3, 10, 0, 0))
    # 退避 wait(30) 立即被 stop 事件唤醒 → 放弃本轮，不累计满 3 次重试
    assert res["reason"] in ("interrupted", "fetch_error")
    assert attempts["n"] < 3
    assert svc.written == []
