"""V1.3 修复回归：进度面板在 phase==LOADING（即使 total==0）时不得误判为空闲。

之前缺陷：update_auto_load_progress 的 LOADING 分支带 `and total > 0` 守卫，
resume_session 复用账本时不重写 total，total 偶为 0 时回退到 idle 分支，
导致「暂停按钮可见但左侧仍显示『自动加载未运行』」的 UI 不一致。
"""
import pytest

from fisher.dash_app.pages.data_center import _derive_auto_load_progress
from fisher.dash_app.services.auto_load_service import (
    PHASE_IDLE, PHASE_LOADING, PHASE_PAUSED, PHASE_DONE, PHASE_ERROR,
)


def _status_text(result):
    # result[0] 为 dbc.Badge 组件（加载中/空闲/...）
    return str(result[0].children)


def _detail_text(result):
    # result[3] 为 auto-load-progress-detail（含『自动加载未运行，请点击开始』等）
    return str(result[3])


def test_loading_with_total_zero_still_shows_loading_not_idle():
    """核心回归：phase==LOADING 且 total==0 时，状态必须显示『加载中』且暂停按钮可见。"""
    state = {"phase": PHASE_LOADING, "total": 0, "done": 0, "failed": 0,
             "pending": 5, "can_resume": False}
    result = _derive_auto_load_progress(state)
    assert "加载中" in _status_text(result), f"徽标应为加载中，实际: {_status_text(result)}"
    assert "未运行" not in _detail_text(result), f"详情不应显示未运行，实际: {_detail_text(result)}"
    assert result[6]["display"] == "block", "phase==LOADING 时暂停按钮必须可见"


def test_loading_with_total_positive_shows_progress():
    state = {"phase": PHASE_LOADING, "total": 100, "done": 30, "failed": 2,
             "pending": 68, "can_resume": False}
    result = _derive_auto_load_progress(state)
    assert "加载中" in _status_text(result)
    assert result[1] == 30  # pct = 30
    assert result[6]["display"] == "block"


def test_idle_shows_not_running():
    state = {"phase": PHASE_IDLE, "total": 0, "done": 0, "failed": 0,
             "pending": 0, "can_resume": False}
    result = _derive_auto_load_progress(state)
    assert "未运行" in _detail_text(result)
    assert "空闲" in _status_text(result)
    assert result[6]["display"] == "none"  # 暂停按钮隐藏


def test_unknown_phase_downgrades_to_idle_safely():
    state = {"phase": "initial_load", "total": 0, "done": 0, "failed": 0,
             "pending": 0, "can_resume": False}
    result = _derive_auto_load_progress(state)
    assert "未运行" in _detail_text(result)
    assert result[4]["display"] == "block"  # 开始按钮可见


def test_resume_session_preserves_total(auto_load_service, monkeypatch):
    """resume_session 复用账本时须把 total 设为账本行数（不为 0）。"""
    svc = auto_load_service
    sid = "resume-total-session"
    with svc._db.transaction():
        svc._ensure_status_table()
        svc._db.execute("DELETE FROM symbol_load_state")
        for i, t in enumerate(["600519.SH", "000001.SZ", "00059.HK"]):
            svc._db.execute(
                "INSERT OR REPLACE INTO symbol_load_state "
                "(ticker, session_id, plan, status, gap_start, attempts) "
                "VALUES (?,?,?,?,?,0)",
                [t, sid, "full", "pending", None])
    with svc._db.transaction():
        svc._set_kv("session_id", sid)
        svc._set_kv("phase", PHASE_DONE)  # 部分失败态
        svc._set_kv("total", "0")         # 模拟 total 被置 0 的脏状态

    def _fake_download(ticker, start):
        return [(ticker, "2024-01-02", 1.0, 1.0, 1.0, 1.0, 1.0, 1000)]
    monkeypatch.setattr(svc, "_download", _fake_download)
    monkeypatch.setattr(svc, "_stop_background", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_start_background", lambda *a, **k: None)

    svc.resume_session()
    assert svc._get_kv("total") == "3", "resume 后 total 应为账本行数 3"
    assert svc._get_kv("phase") == PHASE_LOADING
