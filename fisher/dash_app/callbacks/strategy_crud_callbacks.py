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

TYPE_LABELS = {
    "sma_cross": "均线交叉",
    "macd": "MACD",
    "bollinger": "布林带",
    "rsi": "RSI",
    "buy_and_hold": "买入持有",
    "custom": "自定义DSL",
}


def register_strategy_crud_callbacks(app):
    @app.callback(
        Output("strategy-table-container", "children"),
        Output("strategy-list-store", "data"),
        Input("url", "pathname"),
    )
    def refresh_strategy_table(pathname):
        svc = get_strategy_service()
        strategies = svc.list_strategies()
        table = _build_strategy_list(strategies)
        return table, strategies

    @app.callback(
        Output("strategy-table-container", "children", allow_duplicate=True),
        Output("strategy-list-store", "data", allow_duplicate=True),
        Input("strategy-refresh-trigger", "data"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )
    def refresh_strategy_table_after_action(refresh_data, pathname):
        svc = get_strategy_service()
        strategies = svc.list_strategies()
        table = _build_strategy_list(strategies)
        return table, strategies

    @app.callback(
        Output("strategy-refresh-trigger", "data"),
        Input({"type": "strategy-delete-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_delete(clicks_list):
        ctx = dash.callback_context
        triggered = ctx.triggered
        if not triggered or not any(v for v in (clicks_list or []) if v):
            return no_update
        svc = get_strategy_service()
        for i, t in enumerate(triggered):
            if t.get("value"):
                try:
                    tid = json.loads(t["prop_id"].split(".")[0])
                    name = tid.get("index", "")
                    if name:
                        svc.delete_strategy(name)
                except Exception as e:
                    logger.error("Delete strategy failed: %s", e)
        return datetime.now().isoformat()

    @app.callback(
        Output("strategy-refresh-trigger", "data", allow_duplicate=True),
        Input({"type": "strategy-toggle-switch", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def handle_toggle(values):
        ctx = dash.callback_context
        triggered = ctx.triggered
        if not triggered:
            return no_update
        svc = get_strategy_service()
        for t_item in triggered:
            try:
                tid = json.loads(t_item["prop_id"].split(".")[0])
                name = tid.get("index", "")
                new_val = t_item.get("value")
                if name and new_val is not None:
                    data = svc.get_strategy(name)
                    if data:
                        data["enabled"] = bool(new_val)
                        cfg = StrategyConfig(
                            name=data["name"],
                            type=data["type"],
                            description=data.get("description", ""),
                            params=data.get("params", {}),
                            symbols=data.get("symbols", []),
                            enabled=bool(new_val),
                        )
                        svc.save_strategy(cfg)
            except Exception as e:
                logger.error("Toggle strategy failed: %s", e)
        return datetime.now().isoformat()

    @app.callback(
        Output("strategy-export-download", "data"),
        Input({"type": "strategy-export-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_export(clicks_list):
        ctx = dash.callback_context
        triggered = ctx.triggered
        if not triggered or not any(v for v in (clicks_list or []) if v):
            return no_update
        svc = get_strategy_service()
        for t_item in triggered:
            if t_item.get("value"):
                try:
                    tid = json.loads(t_item["prop_id"].split(".")[0])
                    name = tid.get("index", "")
                    content = svc.export_json(name)
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


def _build_strategy_list(strategies):
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
            dbc.Col("参数", width=3, className="fw-bold"),
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

        row = dbc.Row(
            [
                dbc.Col(html.Strong(name), width=2),
                dbc.Col(html.Small(TYPE_LABELS.get(stype, stype)), width=1),
                dbc.Col(html.Small(sym_display), width=1),
                dbc.Col(html.Small(params_summary, className="text-muted"), width=3),
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
