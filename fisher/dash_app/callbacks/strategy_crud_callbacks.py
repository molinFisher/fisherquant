import json
import base64
import logging
from datetime import datetime

import dash
from dash import Input, Output, State, callback, no_update, html, dcc, ALL
import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)

from fisher.dash_app.services import get_strategy_service
from fisher.dash_app.services.models import StrategyConfig
from fisher.dash_app.services.strategy_data_service import ReadinessReport

TYPE_LABELS = {
    "sma_cross": "均线交叉",
    "macd": "MACD",
    "bollinger": "布林带",
    "rsi": "RSI",
    "buy_and_hold": "买入持有",
    "custom": "自定义DSL",
}


def _compute_readiness_map(strategies):
    """逐策略计算数据就绪状态（列表列用）。宽区间：仅看覆盖度，不判越界。"""
    try:
        from fisher.dash_app.services import get_strategy_data_service
        sds = get_strategy_data_service()
    except Exception:
        return {}
    out = {}
    for s in strategies:
        try:
            rep = sds.check_data_readiness(s, "1970-01-01", "2099-12-31", s.get("symbols"))
        except Exception:
            rep = ReadinessReport(ready=True, blocking=False, missing=[], symbols=[], requires_financials=False)
        out[s.get("name", "")] = (rep.status, rep.missing)
    return out


def _readiness_badge(status, missing):
    if status == "ready":
        return dbc.Badge("✓ 可回测", color="success", className="small")
    if status == "blocked":
        txt = "缺：" + "、".join(m.symbol for m in missing) if missing else "全部标的缺数据"
        return dbc.Badge("✗ 全缺", color="danger", className="small", title=txt)
    txt = "缺：" + "、".join(m.symbol for m in missing) if missing else "部分标的缺数据"
    return dbc.Badge("⚠ 部分缺", color="warning", className="small", title=txt)


def _resolve_pattern_value(trig_id):
    """按结构化 id 从 ctx.inputs_list 中取模式匹配组件的真实触发值。

    背景：模式匹配 id 含非 ASCII 字符（如中文策略名）时，Dash 的
    changedPropIds 使用原始 UTF-8 JSON，而 ctx.triggered / ctx.inputs 的
    key 是 ASCII 转义形式，字符串匹配失败导致 triggered value 恒为 None。
    用 dict 比较可绕开转义差异。
    """
    try:
        for grp in dash.ctx.inputs_list:
            if isinstance(grp, list):
                for item in grp:
                    if item.get("id") == trig_id:
                        return item.get("value")
    except Exception as e:
        logger.error("resolve pattern value failed: %s", e)
    return None


def register_strategy_crud_callbacks(app):
    @app.callback(
        Output("strategy-table-container", "children"),
        Output("strategy-list-store", "data"),
        Input("url", "pathname"),
    )
    def refresh_strategy_table(pathname):
        svc = get_strategy_service()
        strategies = svc.list_strategies()
        table = _build_strategy_list(strategies, _compute_readiness_map(strategies))
        return table, strategies

    @app.callback(
        Output("strategy-table-container", "children", allow_duplicate=True),
        Output("strategy-list-store", "data", allow_duplicate=True),
        Input("strategy-refresh-trigger", "data"),
        prevent_initial_call=True,
    )
    def refresh_strategy_table_after_action(refresh_data):
        # 仅由增删改等动作触发刷新；页面路由变化已由 refresh_strategy_table 处理，
        # 若此处再监听 url 会造成每次进入页面双重渲染表格（DOM 反复重建）。
        if not refresh_data:
            return no_update, no_update
        svc = get_strategy_service()
        strategies = svc.list_strategies()
        table = _build_strategy_list(strategies, _compute_readiness_map(strategies))
        return table, strategies

    @app.callback(
        Output("strategy-refresh-trigger", "data"),
        Input({"type": "strategy-delete-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_delete(clicks_list):
        # 注意：不要用 ctx.triggered[i]["value"] 判断真实点击——模式匹配 id 含
        # 中文时 Dash 的 changedPropIds（原始 UTF-8）与 inputs key（ASCII 转义）
        # 字符串不匹配，value 恒为 None。改用 triggered_id + inputs_list 结构化匹配。
        trig_id = dash.ctx.triggered_id
        if not isinstance(trig_id, dict) or not any(v for v in (clicks_list or []) if v):
            return no_update
        n_clicks = _resolve_pattern_value(trig_id)
        if not n_clicks:
            return no_update
        name = trig_id.get("index", "")
        if not name:
            return no_update
        try:
            get_strategy_service().delete_strategy(name)
        except Exception as e:
            logger.error("Delete strategy failed: %s", e)
            return no_update
        return datetime.now().isoformat()

    @app.callback(
        Output("strategy-refresh-trigger", "data", allow_duplicate=True),
        Input({"type": "strategy-toggle-switch", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def handle_toggle(values):
        # 重要：模式匹配的开关组件在表格每次重渲染时都会以初始 value 触发本回调
        # （prevent_initial_call 挡不住动态新建组件）。若此处无条件写
        # strategy-refresh-trigger，会形成「表格重渲染 → 开关触发 → 写 trigger →
        # 表格重渲染」的无限循环，导致表格 DOM 反复销毁重建，编辑/删除等按钮的
        # n_clicks 被不断重置，真实点击也会被守卫误判为初始触发而失效。
        # 因此：只有开关值与磁盘中的 enabled 状态真正不同时，才落盘并触发刷新。
        trig_id = dash.ctx.triggered_id
        if not isinstance(trig_id, dict):
            return no_update
        name = trig_id.get("index", "")
        # 中文 id 下 ctx.triggered 的 value 不可靠（转义差异），用结构化匹配取值
        new_val = _resolve_pattern_value(trig_id)
        if not name or new_val is None:
            return no_update
        svc = get_strategy_service()
        changed = False
        try:
            data = svc.get_strategy(name)
            if data and bool(data.get("enabled", True)) != bool(new_val):
                cfg = StrategyConfig(
                    name=data["name"],
                    type=data["type"],
                    description=data.get("description", ""),
                    params=data.get("params", {}),
                    symbols=data.get("symbols", []),
                    enabled=bool(new_val),
                )
                svc.save_strategy(cfg)
                changed = True
        except Exception as e:
            logger.error("Toggle strategy failed: %s", e)
        if not changed:
            return no_update
        return datetime.now().isoformat()

    @app.callback(
        Output("strategy-export-download", "data"),
        Input({"type": "strategy-export-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_export(clicks_list):
        trig_id = dash.ctx.triggered_id
        if not isinstance(trig_id, dict) or not any(v for v in (clicks_list or []) if v):
            return no_update
        # 中文 id 下 ctx.triggered 的 value 不可靠（转义差异），用结构化匹配取值
        if not _resolve_pattern_value(trig_id):
            return no_update
        name = trig_id.get("index", "")
        try:
            content = get_strategy_service().export_json(name)
            if content:
                return dcc.send_string(content, filename=f"{name}.json")
        except Exception as e:
            logger.error("Export strategy failed: %s", e)
        return no_update

    @app.callback(
        Output("strategy-refresh-trigger", "data", allow_duplicate=True),
        Output("strategy-import-toast", "children"),
        Input("strategy-import-upload", "contents"),
        State("strategy-import-upload", "filename"),
        prevent_initial_call=True,
    )
    def handle_import(contents, filename):
        if not contents:
            return no_update, ""
        try:
            _, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            svc = get_strategy_service()
            result = svc.import_json(decoded.decode("utf-8"))
            if result.get("status") == "error":
                errors = result.get("errors", [])
                logger.warning("Import strategy errors: %s", errors)
                return no_update, html.Div(
                    [dbc.Alert(f"导入失败: {err}", color="danger", className="py-1 mb-1 small") for err in errors]
                )
            return datetime.now().isoformat(), html.Div(
                dbc.Alert("导入成功", color="success", className="py-1 mb-1 small")
            )
        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.error("Import strategy failed: %s", e)
            return no_update, html.Div(
                dbc.Alert(f"导入失败: {e}", color="danger", className="py-1 mb-1 small")
            )

    @app.callback(
        Output("strategy-import-upload", "contents"),
        Input("strategy-import-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def trigger_import_file_dialog(n_clicks):
        return no_update


def _build_strategy_list(strategies, readiness_map=None):
    if not strategies:
        return html.Div(
            [
                html.H5("暂无策略", className="text-muted text-center mt-4"),
                html.P('点击"新建策略"按钮开始创建', className="text-muted text-center"),
            ]
        )

    header = dbc.Row(
        [
            dbc.Col("名称", width=2, className="fw-bold"),
            dbc.Col("类型", width=1, className="fw-bold"),
            dbc.Col("标的", width=1, className="fw-bold"),
            dbc.Col("参数", width=2, className="fw-bold"),
            dbc.Col("数据就绪", width=1, className="fw-bold"),
            dbc.Col("启用", width=1, className="fw-bold"),
            dbc.Col("创建时间", width=2, className="fw-bold"),
            dbc.Col("操作", width=2, className="fw-bold"),
        ],
        className="border-bottom pb-2 mb-2",
    )

    rows = [header]
    for s in strategies:
        name = s.get("name", "")
        stype = s.get("type", "")
        sym_count = len(s.get("symbols", []))
        sym_display = str(sym_count) if sym_count else "全部"
        params = s.get("params", {})
        if params:
            p_items = [f"{k}:{v}" for k, v in params.items() if k != "dsl_config"]
            if "dsl_config" in params:
                p_items.append("DSL配置")
            params_summary = ", ".join(p_items)[:50]
        else:
            params_summary = "-"
        enabled = s.get("enabled", True)
        created_at = s.get("created_at", "")[:16]

        readiness_cell = html.Div()
        if readiness_map and name in readiness_map:
            r_status, r_missing = readiness_map[name]
            readiness_cell = _readiness_badge(r_status, r_missing)

        row = dbc.Row(
            [
                dbc.Col(html.Strong(name), width=2),
                dbc.Col(html.Small(TYPE_LABELS.get(stype, stype)), width=1),
                dbc.Col(html.Small(sym_display), width=1),
                dbc.Col(html.Small(params_summary, className="text-muted"), width=2),
                dbc.Col(readiness_cell, width=1),
                dbc.Col(
                    dbc.Switch(
                        id={"type": "strategy-toggle-switch", "index": name},
                        value=enabled,
                        className="mt-1",
                    ),
                    width=1,
                ),
                dbc.Col(html.Small(created_at, className="text-muted"), width=2),
                dbc.Col(
                    dbc.ButtonGroup(
                        [
                            dbc.Button("编辑", id={"type": "strategy-edit-btn", "index": name},
                                       color="outline-primary", size="sm"),
                            dbc.Button("导出", id={"type": "strategy-export-btn", "index": name},
                                       color="outline-secondary", size="sm"),
                            dbc.Button("删除", id={"type": "strategy-delete-btn", "index": name},
                                       color="outline-danger", size="sm"),
                        ],
                        size="sm",
                    ),
                    width=2,
                ),
            ],
            className="border-bottom py-2 align-items-center",
        )
        rows.append(row)

    return html.Div(rows)
