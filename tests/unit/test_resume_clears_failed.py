"""复现用户场景：failed 清单点「继续」是否会被清除。

构造：session 含 1 个 FAILED 行（attempts=1, 原因"网络连接失败"），phase=PAUSED。
mock 下载成功，调用 resume_session()，断言该 failed 行被清除（变为 DONE）。
"""
import pytest


def test_resume_session_clears_failed_when_download_ok(auto_load_service, monkeypatch):
    svc = auto_load_service
    svc._retry_backoff = [0, 0, 0]  # 加速 CI：无退避
    svc._ensure_status_table()  # 确保 symbol_load_state 表存在

    # 1) 直接构造账本：1 个 failed 行
    sid = "test-session-001"
    svc._db.execute("DELETE FROM symbol_load_state")
    svc._db.execute(
        "INSERT INTO symbol_load_state (ticker, session_id, plan, status, gap_start, attempts, last_error) "
        "VALUES (?,?,?,?,?,?,?)",
        ["00059.HK", sid, "FULL", "FAILED", None, 1, "ConnectionError: 网络连接失败"])
    svc._set_kv("session_id", sid)
    svc._set_kv("phase", "PAUSED")
    svc._set_kv("total", "1")
    svc._set_kv("done", "0")
    svc._set_kv("failed", "1")

    # 2) mock 下载成功
    def fake_download(ticker, market, plan, gap_start):
        return [["00059.HK", "2024-01-02", 200.0, 201.0, 199.0, 200.5, 500000, 100250000.0, "hk_connect", 1.0]]
    monkeypatch.setattr(svc, "_download", fake_download)

    # 3) 调用「继续」
    svc.resume_session()

    # 4) 等待后台循环跑完
    import time
    for _ in range(50):
        st = svc.get_state()
        if st["phase"] in ("DONE", "ERROR"):
            break
        time.sleep(0.1)

    # 5) 断言 failed 行被清除
    rows = svc._db.query_df(
        "SELECT ticker, status, attempts FROM symbol_load_state WHERE ticker='00059.HK'"
    ).iter_rows(named=True)
    rows = list(rows)
    assert rows, "账本行丢失"
    row = rows[0]
    print(f"AFTER resume: status={row['status']} attempts={row['attempts']}")
    assert row["status"] == "done", (
        f"resume_session 未清除 failed 行：status={row['status']}, attempts={row['attempts']}")
    assert svc.get_state()["failed"] == 0, "get_state.failed 未归零"


def test_resume_session_keeps_failed_when_download_fails(auto_load_service, monkeypatch):
    """对照组：下载仍失败 → failed 行保留且 attempts 递增（证明机制确实在重试）。"""
    svc = auto_load_service
    svc._retry_backoff = [0, 0, 0]
    svc._ensure_status_table()

    sid = "test-session-002"
    svc._db.execute("DELETE FROM symbol_load_state")
    svc._db.execute(
        "INSERT INTO symbol_load_state (ticker, session_id, plan, status, gap_start, attempts, last_error) "
        "VALUES (?,?,?,?,?,?,?)",
        ["00059.HK", sid, "FULL", "FAILED", None, 1, "ConnectionError: 网络连接失败"])
    svc._set_kv("session_id", sid)
    svc._set_kv("phase", "PAUSED")

    def fake_download(ticker, market, plan, gap_start):
        raise ConnectionError("网络连接失败")
    monkeypatch.setattr(svc, "_download", fake_download)

    svc.resume_session()
    import time
    for _ in range(50):
        st = svc.get_state()
        if st["phase"] in ("DONE", "ERROR"):
            break
        time.sleep(0.1)

    rows = svc._db.query_df(
        "SELECT status, attempts FROM symbol_load_state WHERE ticker='00059.HK'"
    ).iter_rows(named=True)
    rows = list(rows)
    print(f"AFTER resume(fail): status={rows[0]['status']} attempts={rows[0]['attempts']}")
    # 下载持续失败：attempts 应递增到 >= retry_max_attempts，仍 failed
    assert rows[0]["status"] == "failed"
    assert rows[0]["attempts"] >= svc._retry_max_attempts
