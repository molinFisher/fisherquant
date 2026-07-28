"""复现「点继续显示未运行(idle)」：覆盖 resume 生命周期多种前置状态。"""
import time

from fisher.dash_app.services.auto_load_service import (
    AutoLoadService, PHASE_IDLE, PHASE_PAUSED, PHASE_LOADING, PHASE_DONE,
    STATUS_PENDING, STATUS_LOADING, STATUS_DONE, STATUS_FAILED,
)


def _seed_interrupted(svc, sid, done=2, pending=3, failed=0, loading=1):
    """构造一个「中途被打断」的会话：部分 done + 部分 pending + 1 个卡住的 loading。"""
    with svc._db.transaction():
        svc._db.execute("DELETE FROM symbol_load_state")
        plan = []
        for i in range(done):
            plan.append(("D%d.SH" % i, sid, "FULL", STATUS_DONE, None, 0))
        for i in range(pending):
            plan.append(("P%d.SH" % i, sid, "FULL", STATUS_PENDING, None, 0))
        for i in range(failed):
            plan.append(("F%d.SH" % i, sid, "FULL", STATUS_FAILED, None, 0))
        for i in range(loading):
            plan.append(("L%d.SH" % i, sid, "FULL", STATUS_LOADING, None, 0))
        for r in plan:
            svc._db.execute(
                "INSERT INTO symbol_load_state "
                "(ticker,session_id,plan,status,gap_start,attempts) VALUES (?,?,?,?,?,?)",
                list(r))
    svc._set_kv("session_id", sid)
    svc._set_kv("phase", PHASE_LOADING)  # 模拟崩溃时悬挂的 loading
    svc._set_kv("total", str(done + pending + failed + loading))
    svc._set_kv("done", str(done))


def _fake_download(ticker, market, plan, gap_start):
    return [[ticker, "2024-01-02", 1.0, 2.0, 0.5, 1.5, 100, 1000.0, market, 1.0]]


def _wait(svc, timeout=30):
    th = svc._thread
    if th is not None:
        th.join(timeout=timeout)
    time.sleep(0.3)


def test_T1_resume_after_interruption(auto_load_service, monkeypatch):
    """正常路径：悬挂 loading + 有 pending → recover→Paused→resume→Done。"""
    svc = auto_load_service
    monkeypatch.setattr(svc, "_download", _fake_download)
    _seed_interrupted(svc, "sessT1", done=2, pending=3, failed=0, loading=1)
    st = svc.recover()
    print("T1 recover:", st["phase"], "pending=", st.get("pending"))
    assert st["phase"] == PHASE_PAUSED, st["phase"]
    svc.resume_session()
    _wait(svc)
    final = svc.get_state()
    print("T1 final:", final["phase"], "done=", final["done"], "failed=", final["failed"])
    assert final["phase"] == PHASE_DONE
    assert final["done"] == 6
    assert final["failed"] == 0


def test_T2_resume_when_recover_idle_but_bars_exist(auto_load_service, monkeypatch):
    """recover 落到 idle(sid 空、bars 有数据) → 点继续应仍能启动(start_session 分支)。

    D-4：自动加载宇宙严格为 auto_load_enabled=TRUE，故这里显式纳入 X.SH，
    以验证 resume→start_session 对「已启用宇宙」的正常加载链路。
    """
    svc = auto_load_service
    monkeypatch.setattr(svc, "_download", _fake_download)
    # recover 的 idle 分支：sid 空 + bars_daily 有数据
    svc._db.execute("INSERT INTO bars_daily "
                    "(ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
                    "VALUES ('X.SH','2024-01-02',1,2,0.5,1.5,100,1000,'a_share',1)")
    # D-4：显式纳入自动加载宇宙（否则空宇宙按设计不自动加载）
    svc._catalog.set_auto_load_enabled("X.SH", True)
    svc._set_kv("session_id", "")
    svc._set_kv("phase", PHASE_IDLE)
    st = svc.recover()
    print("T2 recover:", st["phase"], "sid=", st.get("session_id"))
    # 没有历史会话 → idle，用户点「继续」→ resume_session 应 fallback 到 start_session
    assert st["phase"] == PHASE_IDLE
    svc.resume_session()
    _wait(svc)
    final = svc.get_state()
    print("T2 final:", final["phase"], "total=", final["total"])
    # 至少应进入 loading 并推进，而不是停在 idle 不动
    assert final["phase"] in (PHASE_LOADING, PHASE_DONE)
    assert int(final["total"]) >= 1


def test_T3_resume_sessionid_nonempty_but_ledger_empty(auto_load_service, monkeypatch):
    """sid 非空，但账本已被清空(pending=0) → resume 应 fallback 到 start 而非报 idle。

    D-4：宇宙严格为 auto_load_enabled=TRUE，故显式纳入 Y.SH 以验证 resume→start 链路。
    """
    svc = auto_load_service
    monkeypatch.setattr(svc, "_download", _fake_download)
    monkeypatch.setattr(svc, "_load_index_codes", lambda: ["A.SH", "B.SH"])
    with svc._db.transaction():
        svc._db.execute("DELETE FROM symbol_load_state")
    svc._db.execute("INSERT INTO bars_daily "
                    "(ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
                    "VALUES ('Y.SH','2024-01-02',1,2,0.5,1.5,100,1000,'a_share',1)")
    # D-4：显式纳入自动加载宇宙（否则空宇宙按设计不自动加载）
    svc._catalog.set_auto_load_enabled("Y.SH", True)
    svc._set_kv("session_id", "stale-sid")
    svc._set_kv("phase", PHASE_IDLE)
    st = svc.resume_session()
    print("T3 resume return:", st)
    _wait(svc)
    final = svc.get_state()
    print("T3 final:", final["phase"])
    assert final["phase"] in (PHASE_LOADING, PHASE_DONE)
