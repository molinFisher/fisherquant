import pytest
from datetime import datetime, date, timedelta

from fisher.dash_app.services.auto_load_service import (
    AutoLoadService,
    freshness_baseline,
    market_from_ticker,
    PLAN_FULL, PLAN_GAP, PLAN_SKIP,
    STATUS_PENDING, STATUS_LOADING, STATUS_DONE, STATUS_FAILED,
    PHASE_IDLE, PHASE_LOADING, PHASE_PAUSED, PHASE_DONE, PHASE_ERROR,
)
from fisher.dash_app.services.models import AUTO_LOAD_CFG


# ===========================================================================
# 新鲜度基准纯函数（FR-1.6 / FR-1.7 / 验收#9：可注入时钟 + 周末语义）
# ===========================================================================
class TestFreshnessBaseline:
    def test_a_share_close_1500_after_close(self):
        now = datetime(2026, 7, 27, 16, 0)  # 周一，已收盘
        assert freshness_baseline("a_share", now) == date(2026, 7, 27)

    def test_a_share_before_close_rolls_to_prev(self):
        now = datetime(2026, 7, 27, 14, 0)  # 周一，未收盘
        assert freshness_baseline("a_share", now) == date(2026, 7, 24)  # 上周五

    def test_hk_close_1600_same_day_after(self):
        now = datetime(2026, 7, 27, 16, 30)  # 周一港股已收盘
        assert freshness_baseline("hk_connect", now) == date(2026, 7, 27)

    def test_hk_before_1600_rolls_back(self):
        now = datetime(2026, 7, 27, 15, 30)  # 周一，A股已收但港股未收
        assert freshness_baseline("hk_connect", now) == date(2026, 7, 24)

    def test_saturday_rolls_back_to_friday(self):
        now = datetime(2026, 7, 25, 10, 0)  # 周六
        assert freshness_baseline("a_share", now) == date(2026, 7, 24)

    def test_sunday_rolls_back_to_friday(self):
        now = datetime(2026, 7, 26, 20, 0)  # 周日
        assert freshness_baseline("a_share", now) == date(2026, 7, 24)

    def test_market_from_ticker(self):
        assert market_from_ticker("600519.SH") == "a_share"
        assert market_from_ticker("00700.HK") == "hk_connect"


# ===========================================================================
# 计划生成引擎（FR-1.x）：DB as Source of Truth
# ===========================================================================
class TestBuildPlan:
    def _seed_bar(self, db, ticker, trade_date):
        db.execute(
            "INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            [ticker, trade_date, 100.0, 101.0, 99.0, 100.0, 1000, 1.0,
             "a_share" if ticker.endswith(".SH") or ticker.endswith(".SZ") else "hk_connect", 1.0])

    def test_full_when_no_history(self, auto_load_service):
        plans = auto_load_service.build_plan(["600519.SH", "00700.HK"])
        kinds = {p.ticker: p.kind for p in plans}
        assert kinds["600519.SH"] == PLAN_FULL
        assert kinds["00700.HK"] == PLAN_FULL

    def test_gap_when_stale(self, auto_load_service):
        # 旧数据（远早于任何新鲜度基准）→ GAP
        self._seed_bar(auto_load_service._db, "600519.SH", date(2024, 1, 3))
        plans = auto_load_service.build_plan(["600519.SH"])
        p = plans[0]
        assert p.kind == PLAN_GAP
        assert p.gap_start == date(2024, 1, 4)

    def test_skip_when_fresh(self, auto_load_service):
        # 今天有数据 → SKIP（今天恒定 >= 新鲜度基准）
        self._seed_bar(auto_load_service._db, "600519.SH", date.today())
        plans = auto_load_service.build_plan(["600519.SH"])
        assert plans[0].kind == PLAN_SKIP

    def test_force_full_overrides_history(self, auto_load_service):
        self._seed_bar(auto_load_service._db, "600519.SH", date.today())
        plans = auto_load_service.build_plan(["600519.SH"], force_full=True)
        assert plans[0].kind == PLAN_FULL

    def test_hk_market_classified_by_suffix(self, auto_load_service):
        self._seed_bar(auto_load_service._db, "00700.HK", date(2024, 1, 3))
        plans = auto_load_service.build_plan(["00700.HK"])
        assert plans[0].market == "hk_connect"
        assert plans[0].kind == PLAN_GAP


# ===========================================================================
# 账本会话管理 + 执行器（FR-2.x / FR-2.9 / 验收#1 #2 #12）
# ===========================================================================
class TestLedger:
    def _insert_pending(self, svc, ticker, plan=PLAN_FULL, gap_start=None, session="s1"):
        svc._db.execute(
            "INSERT INTO symbol_load_state (ticker, session_id, plan, status, gap_start, attempts) "
            "VALUES (?,?,?,?,?,0)",
            [ticker, session, plan, STATUS_PENDING,
             gap_start.isoformat() if gap_start else None])

    def test_session_start_builds_ledger(self, auto_load_service):
        # 全新库 → 全部 FULL，账本行数 = 宇宙大小（mock 网络下为 3 A + 80 HK）
        result = auto_load_service.start_session(force_full=False)
        assert result["phase"] == PHASE_LOADING
        total = int(auto_load_service._get_kv("total", "0"))
        rows = auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM symbol_load_state")["c"][0]
        assert rows == total
        assert total > 0
        # 清理后台线程，避免测试间串扰
        auto_load_service._stop_event.set()
        auto_load_service._thread.join(timeout=5)

    def test_run_batch_marks_done_and_writes_bars(self, auto_load_service):
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL)
        more = auto_load_service._run_batch(10)
        assert more is True
        st = auto_load_service._db.query_df(
            "SELECT status FROM symbol_load_state WHERE ticker='600519.SH'")["status"].to_list()[0]
        assert st == STATUS_DONE
        n = auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='600519.SH'")["c"][0]
        assert n > 0

    def test_idempotent_rerun_no_duplicate(self, auto_load_service):
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL)
        auto_load_service._run_batch(10)
        first = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='600519.SH'")["c"][0])
        # 再次以相同计划跑（状态翻回 pending 模拟重跑）：INSERT OR REPLACE 不应产生重复行
        auto_load_service._db.execute(
            "UPDATE symbol_load_state SET status=? WHERE ticker=?", [STATUS_PENDING, "600519.SH"])
        auto_load_service._run_batch(10)
        second = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='600519.SH'")["c"][0])
        assert second == first

    def test_failed_row_records_attempt(self, auto_load_service, monkeypatch):
        import akshare as ak
        def boom(*a, **k):
            raise RuntimeError("network down")
        monkeypatch.setattr(ak, "stock_zh_a_daily", boom, raising=False)
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL)
        auto_load_service._run_batch(10)
        row = auto_load_service._db.query_df(
            "SELECT status, attempts FROM symbol_load_state WHERE ticker='600519.SH'")
        assert row["status"].to_list()[0] == STATUS_FAILED
        assert row["attempts"].to_list()[0] == 1

    def test_resume_reuses_ledger_and_completes(self, auto_load_service):
        # 仅 2 条待处理，resume 应复用账本并跑完
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL, session="s2")
        self._insert_pending(auto_load_service, "00700.HK", PLAN_FULL, session="s2")
        auto_load_service._set_kv("session_id", "s2")
        auto_load_service._set_kv("phase", PHASE_PAUSED)
        auto_load_service.resume_session()
        auto_load_service._thread.join(timeout=10)
        done = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM symbol_load_state WHERE status=?", [STATUS_DONE])["c"][0])
        assert done == 2

    def test_interrupted_recovery_loading_to_pending(self, auto_load_service):
        # 模拟崩溃遗留 loading 行；recover 不自动开跑，仅翻回 pending
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL, session="s3")
        auto_load_service._db.execute(
            "UPDATE symbol_load_state SET status=? WHERE ticker=?", [STATUS_LOADING, "600519.SH"])
        auto_load_service._set_kv("session_id", "s3")
        state = auto_load_service.recover()
        st = auto_load_service._db.query_df(
            "SELECT status FROM symbol_load_state WHERE ticker='600519.SH'")["status"].to_list()[0]
        assert st == STATUS_PENDING           # 中断恢复：loading → pending
        assert state["phase"] == PHASE_PAUSED  # 等待用户「继续」
        assert state["can_resume"] is True

    def test_cross_restart_resume(self, auto_load_service):
        # 跨重启语义：账本持久化在 DB，recover 后能继续（验收#3）
        self._insert_pending(auto_load_service, "600519.SH", PLAN_FULL, session="s4")
        self._insert_pending(auto_load_service, "000001.SZ", PLAN_FULL, session="s4")
        auto_load_service._set_kv("session_id", "s4")
        auto_load_service._set_kv("phase", PHASE_PAUSED)
        # 模拟重启：新建服务实例（同一 DB），调用 recover
        svc2 = AutoLoadService(auto_load_service._db, auto_load_service._limiter,
                               auto_load_service._scheduler)
        state = svc2.recover()
        assert state["can_resume"] is True
        assert int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM symbol_load_state")["c"][0]) == 2
        svc2.resume_session()
        svc2._thread.join(timeout=10)
        done = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM symbol_load_state WHERE status=?", [STATUS_DONE])["c"][0])
        assert done == 2


# ===========================================================================
# 增量更新：市场路由 + 全量覆盖（修复 P6 / P7）
# ===========================================================================
class TestIncremental:
    def test_market_routing_and_full_coverage(self, auto_load_service):
        # 既有 A 股也有港股，且都过期 → 增量应两路都更新且 market 列正确
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["600519.SH", date(2024, 1, 3), 100.0, 101.0, 99.0, 100.0, 1000, 1.0, "a_share", 1.0])
        auto_load_service._db.execute(
            "INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            ["00700.HK", date(2024, 1, 3), 200.0, 201.0, 199.0, 200.0, 500, 1.0, "hk_connect", 1.0])
        result = auto_load_service.incremental_update()
        assert result["phase"] == "incremental"
        assert result["processed"] == 2
        # A 股走 stock_zh_a_daily（mock 2 行），港股走 stock_hk_daily（mock 1 行）
        a_n = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='600519.SH'")["c"][0])
        hk_n = int(auto_load_service._db.query_df(
            "SELECT COUNT(*) AS c FROM bars_daily WHERE ticker='00700.HK'")["c"][0])
        assert a_n == 2
        assert hk_n == 1

    def test_incremental_no_data_handled(self, auto_load_service):
        auto_load_service._db.execute("DELETE FROM bars_daily")
        result = auto_load_service.incremental_update()
        assert result["phase"] == "incremental"
        assert result["processed"] == 0


# ===========================================================================
# 状态查询兼容（首页/进度回调）
# ===========================================================================
class TestState:
    def test_get_state_shape(self, auto_load_service):
        st = auto_load_service.get_state()
        for k in ("phase", "session_id", "total", "done", "failed", "pending", "can_resume"):
            assert k in st

    def test_get_progress_legacy_aliases(self, auto_load_service):
        prog = auto_load_service.get_progress()
        for k in ("phase", "current", "total", "skipped"):
            assert k in prog
