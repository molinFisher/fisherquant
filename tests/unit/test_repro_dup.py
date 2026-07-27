import pytest
from fisher.dash_app.services.auto_load_service import AutoLoadService, PHASE_LOADING


def test_duplicate_ticker_in_universe_no_longer_raises(auto_load_service, monkeypatch):
    """回归：成分股清单含重复 ticker（如 600482.SH 出现两次）时，
    start_session 必须去重并成功建立账本，而非抛 duplicate key 让「开始」失败。"""
    monkeypatch.setattr(
        auto_load_service, "_load_index_codes",
        lambda: ["600519.SH", "600482.SH", "600482.SH", "000001.SZ"],
    )
    state = auto_load_service.start_session(force_full=False)
    assert state["phase"] == PHASE_LOADING
    # 账本应去重：仅 3 个标的（600482.SH 只计一次）
    assert int(auto_load_service.get_status("total", "0")) == 3


def test_universe_dedup_preserves_order(auto_load_service, monkeypatch):
    monkeypatch.setattr(
        auto_load_service, "_load_index_codes",
        lambda: ["600519.SH", "600519.SH", "000001.SZ", "300750.SZ"],
    )
    assert auto_load_service._snapshot_universe() == [
        "600519.SH", "000001.SZ", "300750.SZ",
    ]
