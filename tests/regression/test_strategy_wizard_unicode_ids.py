"""回归测试：策略中心模式匹配回调对中文（非 ASCII）策略名的处理。

Bug 背景（2026-07-30 修复）：
1. Dash 对模式匹配 id 含非 ASCII 字符时，changedPropIds 使用原始 UTF-8 JSON
   （{"index":"MACD策略",...}），而 ctx.triggered / ctx.inputs 的 key 是 ASCII
   转义形式（{"index":"MACD\\u7b56\\u7565",...}），字符串匹配失败导致
   triggered[0]["value"] 恒为 None——中文策略名下「编辑/删除/开关/导出」按钮
   的真实点击全部被守卫误判为初始渲染触发而静默失效。
   修复：改用 ctx.triggered_id（结构化 dict）+ inputs_list 按 dict 匹配取值。
2. handle_toggle 无条件写 strategy-refresh-trigger，与表格重渲染形成无限循环，
   表格 DOM 反复销毁重建导致按钮点击丢失。
   修复：仅当开关值与磁盘 enabled 状态真正不同时才落盘并触发刷新。
"""
import sys
import types
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.helpers.dash_harness import FakeDashApp, capture_dash_callbacks

EDIT_ID = {"type": "strategy-edit-btn", "index": "MACD策略"}

STRATEGY_DATA = {
    "name": "MACD策略",
    "type": "macd",
    "description": "测试",
    "params": {"fast": 12, "slow": 26, "signal": 9},
    "symbols": [],
    "enabled": True,
}


class _StubCtx(types.SimpleNamespace):
    pass


def _make_ctx(triggered_id, inputs_list, triggered=None):
    return _StubCtx(
        triggered_id=triggered_id,
        inputs_list=inputs_list,
        triggered=triggered or [],
    )


class _FakeService:
    def __init__(self):
        self.deleted = []
        self.saved = []

    def get_strategy(self, name):
        if name == STRATEGY_DATA["name"]:
            return dict(STRATEGY_DATA)
        return None

    def delete_strategy(self, name):
        self.deleted.append(name)

    def save_strategy(self, cfg):
        self.saved.append(cfg)
        return {"status": "ok"}

    def export_json(self, name):
        return "{}" if name == STRATEGY_DATA["name"] else None


@pytest.fixture()
def wizard_app(monkeypatch):
    """注册向导回调到 FakeDashApp，并 stub 掉策略服务。"""
    import fisher.dash_app.callbacks.strategy_wizard_callbacks as wiz

    svc = _FakeService()
    monkeypatch.setattr(wiz, "get_strategy_service", lambda: svc)
    app = FakeDashApp()
    with capture_dash_callbacks(app):
        wiz.register_strategy_wizard_callbacks(app)
    return app, wiz, svc


@pytest.fixture()
def crud_app(monkeypatch):
    import fisher.dash_app.callbacks.strategy_crud_callbacks as crud

    svc = _FakeService()
    monkeypatch.setattr(crud, "get_strategy_service", lambda: svc)
    app = FakeDashApp()
    with capture_dash_callbacks(app):
        crud.register_strategy_crud_callbacks(app)
    return app, crud, svc


def _find_cb(app, output_id, func_name):
    """同一 Output 可能有多个回调（allow_duplicate），按函数名精确选取。"""
    for f in app._reg._by_id[output_id]:
        if f.__name__ == func_name:
            return f
    raise KeyError(f"callback {func_name} not found for {output_id}")


def test_edit_click_with_chinese_name_opens_modal(wizard_app, monkeypatch):
    """真实点击中文名编辑按钮 → 弹窗必须打开（此前因转义差异被静默拦截）。"""
    import dash
    app, wiz, svc = wizard_app
    cb = _find_cb(app, "strategy-wizard-modal.is_open", "open_wizard_for_create")

    # 模拟：真实点击（inputs_list 中该按钮 value=1），但 ctx.triggered 的
    # value 因 Dash 转义 bug 为 None——修复后的代码不应再依赖它。
    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id=EDIT_ID,
        inputs_list=[
            {"id": "strategy-create-btn", "property": "n_clicks", "value": None},
            [{"id": EDIT_ID, "property": "n_clicks", "value": 1}],
        ],
        triggered=[{"prop_id": '{"index":"MACD策略","type":"strategy-edit-btn"}.n_clicks', "value": None}],
    ))
    result = cb(None, [1])
    is_open, body, footer, title, state, edit_id, confirm = result
    assert is_open is True
    assert "MACD策略" in title
    assert state["data"]["name"] == "MACD策略"
    assert edit_id == "MACD策略"


def test_edit_initial_render_does_not_open_modal(wizard_app, monkeypatch):
    """表格渲染触发（n_clicks=None）不得打开弹窗（防止进页面默认弹编辑框）。"""
    import dash
    from dash import no_update
    app, wiz, svc = wizard_app
    cb = _find_cb(app, "strategy-wizard-modal.is_open", "open_wizard_for_create")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id=EDIT_ID,
        inputs_list=[
            {"id": "strategy-create-btn", "property": "n_clicks", "value": None},
            [{"id": EDIT_ID, "property": "n_clicks", "value": None}],
        ],
    ))
    result = cb(None, [None])
    assert all(r is no_update for r in result)


def test_create_click_opens_modal(wizard_app, monkeypatch):
    import dash
    app, wiz, svc = wizard_app
    cb = _find_cb(app, "strategy-wizard-modal.is_open", "open_wizard_for_create")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id="strategy-create-btn",
        inputs_list=[
            {"id": "strategy-create-btn", "property": "n_clicks", "value": 1},
            [],
        ],
    ))
    result = cb(1, [])
    assert result[0] is True
    assert result[3] == "新建策略"


def test_cancel_button_closes_modal(wizard_app, monkeypatch):
    """取消按钮 → is_open=False（原始 Bug：取消无效）。"""
    import dash
    app, wiz, svc = wizard_app
    nav = _find_cb(app, "strategy-wizard-modal.is_open", "handle_wizard_navigation")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id="wizard-cancel-btn",
        inputs_list=[],
        triggered=[{"prop_id": "wizard-cancel-btn.n_clicks", "value": 1}],
    ))
    result = nav(None, None, None, 1, {"step": 0, "data": {}}, None, "", None, "", [])
    assert result[0] is False
    assert result[4] == {"step": 0, "data": {}}


def test_delete_with_chinese_name(crud_app, monkeypatch):
    import dash
    app, crud, svc = crud_app
    del_id = {"type": "strategy-delete-btn", "index": "MACD策略"}
    cb = _find_cb(app, "strategy-refresh-trigger.data", "handle_delete")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id=del_id,
        inputs_list=[[{"id": del_id, "property": "n_clicks", "value": 1}]],
    ))
    result = cb([1])
    assert result is not None and result != ()
    assert svc.deleted == ["MACD策略"]


def test_toggle_same_value_no_refresh_loop(crud_app, monkeypatch):
    """开关值与磁盘一致时必须 no_update，否则会形成表格无限刷新循环。"""
    import dash
    from dash import no_update
    app, crud, svc = crud_app
    tog_id = {"type": "strategy-toggle-switch", "index": "MACD策略"}
    toggle = _find_cb(app, "strategy-refresh-trigger.data", "handle_toggle")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id=tog_id,
        inputs_list=[[{"id": tog_id, "property": "value", "value": True}]],  # 与磁盘 enabled=True 相同
    ))
    result = toggle([True])
    assert result is no_update
    assert svc.saved == []


def test_toggle_changed_value_saves_and_refreshes(crud_app, monkeypatch):
    import dash
    from dash import no_update
    app, crud, svc = crud_app
    tog_id = {"type": "strategy-toggle-switch", "index": "MACD策略"}
    toggle = _find_cb(app, "strategy-refresh-trigger.data", "handle_toggle")

    monkeypatch.setattr(dash, "ctx", _make_ctx(
        triggered_id=tog_id,
        inputs_list=[[{"id": tog_id, "property": "value", "value": False}]],  # 磁盘为 True → 变化
    ))
    result = toggle([False])
    assert result is not no_update
    assert len(svc.saved) == 1
    assert svc.saved[0].enabled is False
