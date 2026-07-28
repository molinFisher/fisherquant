import time
from datetime import datetime

from fisher.dash_app.pages import data_center
from fisher.dash_app.services.auto_load_service import freshness_baseline
from tests.helpers.dash_harness import capture_dash_callbacks


def _wait(svc, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = svc.get_state()
        alive = svc._thread is not None and svc._thread.is_alive()
        if st["phase"] == "done" and not alive:
            return
        time.sleep(0.02)


def _collect_ids(node, acc):
    if node is None:
        return
    nid = getattr(node, "id", None)
    if nid:
        acc.append(nid)
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            if child is not None:
                _collect_ids(child, acc)
    elif children is not None:
        _collect_ids(children, acc)


def test_layout_has_p2_components():
    """#41/#42：自动加载页含失败清单、重试按钮、彻底重下开关组件。"""
    tab = data_center._create_auto_load_tab()
    ids = []
    _collect_ids(tab, ids)
    for needed in ["auto-load-failed-collapse", "auto-load-retry-failed-btn",
                   "auto-load-force-full-check"]:
        assert needed in ids, needed


def test_reload_confirm_label_toggle():
    """#42：勾选彻底重下 → 确认按钮变红并提示全量重下。"""
    with capture_dash_callbacks() as app:
        data_center.register_data_center_callbacks(app)
        cb = app.get_callback("auto-load-reload-confirm")
        assert cb(False) == ("确认重新加载", "primary")
        assert cb(True) == ("清空并全量重下", "danger")


def test_failed_list_renders(monkeypatch):
    """#41：存在最终失败时展开清单并渲染（ticker/名称/原因/次数）。"""
    class FakeSvc:
        def get_state(self):
            return {"failed": 1}

        def get_failed(self):
            return [{"ticker": "600519.SH", "name": "贵州茅台",
                     "attempts": 3, "reason": "请求超时"}]

    import fisher.dash_app.services as svc_mod
    monkeypatch.setattr(svc_mod, "get_auto_load_service", lambda: FakeSvc())
    with capture_dash_callbacks() as app:
        data_center.register_data_center_callbacks(app)
        cb = app.get_callback("auto-load-failed-collapse")
        is_open, items, style = cb(0)
        assert is_open is True
        assert style["display"] == "block"
        assert len(items) == 1


def test_reload_force_full_marks_plan(auto_load_service):
    """#42：彻底重下开关 → reload(force_full=True) 生成全量 FULL 计划，普通 reload 复用历史(SKIP)。"""
    svc = auto_load_service
    # 用动态新鲜基准日写入，避免硬编码日期随真实时间推移而过时(导致 SKIP 误判为 GAP)
    fresh_date = freshness_baseline("a_share", datetime.now()).isoformat()
    svc._db.execute(
        "INSERT INTO bars_daily (ticker,trade_date,open,high,low,close,volume,amount,market,adj_factor) "
        f"VALUES ('600519.SH','{fresh_date}',1,1,1,1,1,1.0,'a_share',1.0)")
    svc._db.execute(
        "INSERT INTO symbol_dict (ticker,code,name,market) VALUES ('600519.SH','600519','茅台','a_share')")
    # 普通 reload：库有数据 → 至少 600519 被 SKIP
    svc.reload(force_full=False)
    _wait(svc)
    plans = svc.build_plan(svc._snapshot_universe(), force_full=False)
    assert any(p.kind == "SKIP" for p in plans)
    # 彻底重下：全部 FULL
    svc.reload(force_full=True)
    _wait(svc)
    plans2 = svc.build_plan(svc._snapshot_universe(), force_full=True)
    assert all(p.kind == "FULL" for p in plans2)
    assert svc.get_state()["force_full"] is True
