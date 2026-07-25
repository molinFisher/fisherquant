import json
from datetime import datetime

import dash
from dash import Input, Output, State, callback, no_update, html, dcc, ALL
import dash_bootstrap_components as dbc

from fisher.dash_app.services import get_strategy_service
from fisher.dash_app.services.models import StrategyConfig
from fisher.dash_app.pages.strategy_center import (
    _render_wizard_step_0,
    _render_wizard_step_1,
    _render_wizard_step_2,
    _render_wizard_step_3,
)
from fisher.strategy.dsl import validate_dsl

TEMPLATES = {
    "sma": {
        "name": "SMA均线交叉", "type": "sma_cross",
        "description": "SMA均线交叉策略 - 快线上穿慢线买入，下穿卖出",
        "params": {"fast": 5, "slow": 20}, "symbols": [], "enabled": True,
    },
    "macd": {
        "name": "MACD策略", "type": "macd",
        "description": "MACD金叉死叉策略 - DIF上穿DEA买入，下穿卖出",
        "params": {"fast": 12, "slow": 26, "signal": 9}, "symbols": [], "enabled": True,
    },
    "bollinger": {
        "name": "布林带策略", "type": "bollinger",
        "description": "布林带策略 - 价格跌破下轨买入，突破上轨卖出",
        "params": {"period": 20, "std": 2}, "symbols": [], "enabled": True,
    },
    "rsi": {
        "name": "RSI策略", "type": "rsi",
        "description": "RSI超买超卖策略 - 超卖区买入，超买区卖出",
        "params": {"period": 14, "overbought": 70, "oversold": 30}, "symbols": [], "enabled": True,
    },
    "buyhold": {
        "name": "买入持有", "type": "buy_and_hold",
        "description": "买入持有策略 - 策略启动时买入，长期持有",
        "params": {}, "symbols": [], "enabled": True,
    },
}


def register_strategy_wizard_callbacks(app):
    @app.callback(
        Output("strategy-wizard-modal", "is_open"),
        Output("strategy-wizard-body", "children"),
        Output("strategy-wizard-footer", "children"),
        Output("strategy-wizard-title", "children"),
        Output("strategy-wizard-state", "data"),
        Output("strategy-edit-id", "data"),
        Output("confirm-delete-strategy-name", "data"),
        Input("strategy-create-btn", "n_clicks"),
        Input({"type": "strategy-edit-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def open_wizard_for_create(create_clicks, edit_clicks_list):
        triggered = dash.ctx.triggered[0] if dash.ctx.triggered else None
        if not triggered:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update

        prop_id = triggered["prop_id"]
        if "strategy-create-btn" in prop_id:
            new_state = {"step": 0, "data": {}}
            body = _render_wizard_step_0()
            footer = _build_wizard_footer(0)
            return True, body, footer, "新建策略", new_state, None, ""

        if "strategy-edit-btn" in prop_id:
            try:
                triggered_id = json.loads(prop_id.split(".")[0])
                name = triggered_id.get("index", "")
            except Exception:
                return no_update, no_update, no_update, no_update, no_update, no_update, no_update

            svc = get_strategy_service()
            data = svc.get_strategy(name)
            if data is None:
                return no_update, no_update, no_update, no_update, no_update, no_update, no_update
            step = 0
            wizard_state = {"step": step, "data": data}
            body = _render_wizard_body(step, data)
            footer = _build_wizard_footer(step)
            return True, body, footer, f"编辑策略: {name}", wizard_state, name, ""

        return no_update, no_update, no_update, no_update, no_update, no_update, no_update

    @app.callback(
        Output("strategy-wizard-modal", "is_open", allow_duplicate=True),
        Output("strategy-wizard-body", "children", allow_duplicate=True),
        Output("strategy-wizard-footer", "children", allow_duplicate=True),
        Output("strategy-wizard-title", "children", allow_duplicate=True),
        Output("strategy-wizard-state", "data", allow_duplicate=True),
        Input("wizard-prev-btn", "n_clicks"),
        Input("wizard-next-btn", "n_clicks"),
        Input("wizard-save-btn", "n_clicks"),
        Input("wizard-cancel-btn", "n_clicks"),
        State("strategy-wizard-state", "data"),
        State("strategy-edit-id", "data"),
        State("wizard-name", "value"),
        State("wizard-type", "value"),
        State("wizard-description", "value"),
        State("wizard-symbols", "value"),
        prevent_initial_call=True,
    )
    def handle_wizard_navigation(
        prev_clicks, next_clicks, save_clicks, cancel_clicks,
        current_state, edit_id,
        name_val, type_val, description_val, symbols_val,
    ):
        triggered = dash.ctx.triggered[0]["prop_id"].split(".")[0] if dash.ctx.triggered else ""
        step = (current_state or {}).get("step", 0)
        wizard_data = (current_state or {}).get("data", {})

        if triggered == "wizard-cancel-btn":
            return False, "", "", "", {"step": 0, "data": {}}

        if triggered == "wizard-prev-btn":
            step = max(0, step - 1)
            new_state = {"step": step, "data": wizard_data}
            body = _render_wizard_body(step, wizard_data)
            footer = _build_wizard_footer(step)
            return True, body, footer, _get_wizard_title(edit_id), new_state

        if triggered == "wizard-next-btn":
            if step == 0:
                if not name_val or not name_val.strip():
                    body = _render_wizard_step_0({"name": name_val, "type": type_val, "description": description_val})
                    new_state = {"step": 0, "data": wizard_data}
                    footer = _build_wizard_footer(0)
                    footer_with_err = _add_error_to_footer(footer, "请输入策略名称")
                    return True, body, footer_with_err, _get_wizard_title(edit_id), new_state
                if not type_val:
                    body = _render_wizard_step_0({"name": name_val, "type": type_val, "description": description_val})
                    new_state = {"step": 0, "data": wizard_data}
                    footer = _build_wizard_footer(0)
                    footer_with_err = _add_error_to_footer(footer, "请选择策略类型")
                    return True, body, footer_with_err, _get_wizard_title(edit_id), new_state
                wizard_data["name"] = name_val.strip()
                wizard_data["type"] = type_val
                wizard_data["description"] = description_val or ""

            elif step == 1:
                current_type = wizard_data.get("type", "")
                params = _collect_params_from_states()
                if current_type == "custom":
                    dsl_config = params.get("dsl_config", "{}")
                    if dsl_config.strip():
                        try:
                            dsl_dict = json.loads(dsl_config)
                            dsl_errors = validate_dsl(dsl_dict)
                            if dsl_errors:
                                footer = _build_wizard_footer(1)
                                footer_with_err = _add_error_to_footer(footer, "; ".join(dsl_errors))
                                return True, _render_wizard_step_1(current_type, wizard_data), footer_with_err, _get_wizard_title(edit_id), {"step": 1, "data": wizard_data}
                            params["dsl_config"] = dsl_dict
                        except json.JSONDecodeError:
                            footer = _build_wizard_footer(1)
                            footer_with_err = _add_error_to_footer(footer, "JSON格式错误")
                            return True, _render_wizard_step_1(current_type, wizard_data), footer_with_err, _get_wizard_title(edit_id), {"step": 1, "data": wizard_data}
                    else:
                        params["dsl_config"] = {}
                wizard_data["params"] = params

            elif step == 2:
                wizard_data["symbols"] = symbols_val or []

            step = min(3, step + 1)
            new_state = {"step": step, "data": wizard_data}
            body = _render_wizard_body(step, wizard_data)
            footer = _build_wizard_footer(step)
            return True, body, footer, _get_wizard_title(edit_id), new_state

        if triggered == "wizard-save-btn":
            name = wizard_data.get("name", "")
            stype = wizard_data.get("type", "")
            params = wizard_data.get("params", {})
            symbols = wizard_data.get("symbols", []) or []
            desc = wizard_data.get("description", "")

            svc = get_strategy_service()
            existing = svc.get_strategy(name)

            cfg = StrategyConfig(
                name=name,
                type=stype,
                description=desc,
                params=params,
                symbols=symbols,
                enabled=existing.get("enabled", True) if existing else True,
            )
            svc.save_strategy(cfg)
            return False, "", "", "", {"step": 0, "data": {}}

        return no_update, no_update, no_update, no_update, no_update

    @app.callback(
        Output("strategy-wizard-modal", "is_open", allow_duplicate=True),
        Output("strategy-wizard-body", "children", allow_duplicate=True),
        Output("strategy-wizard-footer", "children", allow_duplicate=True),
        Output("strategy-wizard-title", "children", allow_duplicate=True),
        Output("strategy-wizard-state", "data", allow_duplicate=True),
        Output("strategy-edit-id", "data", allow_duplicate=True),
        Input("template-sma", "n_clicks"),
        Input("template-macd", "n_clicks"),
        Input("template-bollinger", "n_clicks"),
        Input("template-rsi", "n_clicks"),
        Input("template-buyhold", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_template(t1, t2, t3, t4, t5):
        triggered = dash.ctx.triggered[0]["prop_id"].split(".")[0] if dash.ctx.triggered else ""
        tmpl_map = {
            "template-sma": "sma", "template-macd": "macd",
            "template-bollinger": "bollinger", "template-rsi": "rsi",
            "template-buyhold": "buyhold",
        }
        key = tmpl_map.get(triggered)
        if not key:
            return no_update, no_update, no_update, no_update, no_update, no_update

        tmpl = json.loads(json.dumps(TEMPLATES[key]))
        tmpl["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmpl["updated_at"] = tmpl["created_at"]
        base_name = tmpl["name"]

        svc = get_strategy_service()
        existing_names = {s.get("name", "") for s in svc.list_strategies()}
        unique_name = base_name
        counter = 1
        while unique_name in existing_names:
            unique_name = f"{base_name} ({counter})"
            counter += 1
        tmpl["name"] = unique_name

        cfg = StrategyConfig(
            name=tmpl["name"], type=tmpl["type"],
            description=tmpl.get("description", ""),
            params=tmpl.get("params", {}),
            symbols=tmpl.get("symbols", []),
            enabled=tmpl.get("enabled", True),
        )
        svc.save_strategy(cfg)
        return no_update, no_update, no_update, no_update, no_update, no_update

    @app.callback(
        Output("wizard-symbols", "options"),
        Input("strategy-wizard-modal", "is_open"),
    )
    def load_symbol_pool_options(is_open):
        if is_open:
            return _get_cached_symbols()
        return []

    @app.callback(
        Output("strategy-wizard-body", "children", allow_duplicate=True),
        Input("wizard-type", "value"),
        State("strategy-wizard-state", "data"),
        prevent_initial_call=True,
    )
    def update_params_form_on_type_change(type_val, wizard_state):
        if not type_val:
            return no_update
        if not wizard_state or wizard_state.get("step") != 1:
            return no_update
        data = wizard_state.get("data", {})
        data["type"] = type_val
        return _render_wizard_step_1(type_val, data)


def _get_cached_symbols():
    try:
        from fisher.dash_app.services import get_data_service
        svc = get_data_service()
        rows = svc.get_cached_table(market_filter="all")
        return [{"label": r["ticker"], "value": r["ticker"]} for r in rows]
    except Exception:
        return []


def _add_error_to_footer(footer_elements, error_msg):
    if not isinstance(footer_elements, list):
        footer_elements = [footer_elements] if footer_elements else []
    alert = html.Div(
        dbc.Alert(error_msg, color="danger", className="py-1 px-2 small mb-0 me-2"),
        className="flex-grow-1",
    )
    return [alert] + list(footer_elements)


def _render_wizard_body(step, data):
    stype = data.get("type", "")
    if step == 0:
        return _render_wizard_step_0(data)
    elif step == 1:
        return _render_wizard_step_1(stype, data)
    elif step == 2:
        return _render_wizard_step_2(data)
    elif step == 3:
        return _render_wizard_step_3(data)
    return _render_wizard_step_0(data)


def _build_wizard_footer(step):
    buttons = []
    if step > 0:
        buttons.append(dbc.Button("上一步", id="wizard-prev-btn", color="secondary", className="me-2"))
    buttons.append(dbc.Button("取消", id="wizard-cancel-btn", color="link", className="me-2"))
    if step < 3:
        buttons.append(dbc.Button("下一步", id="wizard-next-btn", color="primary"))
    else:
        buttons.append(dbc.Button("保存策略", id="wizard-save-btn", color="success"))
    return buttons


def _get_wizard_title(edit_id):
    return f"编辑策略: {edit_id}" if edit_id else "新建策略"


def _collect_params_from_states():
    states = dash.ctx.states
    stype = ""
    wizard_data = {}

    if isinstance(states, dict):
        wizard_state_val = states.get("strategy-wizard-state.data", {})
        if isinstance(wizard_state_val, dict):
            wizard_data = wizard_state_val.get("data", {})
            stype = wizard_data.get("type", "")
    else:
        for s in (states or []):
            if isinstance(s, dict):
                for k, v in s.items():
                    if "strategy-wizard-state" in k and isinstance(v, dict):
                        wizard_data = v.get("data", {})
                        stype = wizard_data.get("type", "")
                        break
            if stype:
                break

    if not stype:
        stype = wizard_data.get("type", "")

    result = {}
    if stype == "sma_cross":
        result = {"fast": int(wizard_data.get("params", {}).get("fast", 5)),
                  "slow": int(wizard_data.get("params", {}).get("slow", 20))}
    elif stype == "macd":
        result = {"fast": int(wizard_data.get("params", {}).get("fast", 12)),
                  "slow": int(wizard_data.get("params", {}).get("slow", 26)),
                  "signal": int(wizard_data.get("params", {}).get("signal", 9))}
    elif stype == "bollinger":
        result = {"period": int(wizard_data.get("params", {}).get("period", 20)),
                  "std": float(wizard_data.get("params", {}).get("std", 2))}
    elif stype == "rsi":
        result = {"period": int(wizard_data.get("params", {}).get("period", 14)),
                  "overbought": float(wizard_data.get("params", {}).get("overbought", 70)),
                  "oversold": float(wizard_data.get("params", {}).get("oversold", 30))}
    elif stype == "buy_and_hold":
        result = {}
    elif stype == "custom":
        dsl = wizard_data.get("params", {}).get("dsl_config", "{}")
        result = {"dsl_config": dsl if isinstance(dsl, str) else json.dumps(dsl, ensure_ascii=False)}
    return result
