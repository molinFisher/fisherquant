import json
import os
from pathlib import Path

import dash
from dash import Input, Output, State, callback, no_update, html
import dash_bootstrap_components as dbc

SETTINGS_FILE = Path("config/settings.json")


def _load_settings():
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_settings(data):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def register_settings_callbacks(app):
    @app.callback(
        Output("settings-save-status", "children"),
        Input("cfg-params-save-btn", "n_clicks"),
        State("cfg-commission", "value"),
        State("cfg-min-commission", "value"),
        State("cfg-slippage", "value"),
        State("cfg-capital", "value"),
        State("cfg-stamp-duty", "value"),
        State("cfg-risk-free", "value"),
        prevent_initial_call=True,
    )
    def save_params(n, commission, min_comm, slippage, capital, stamp, risk_free):
        settings = _load_settings()
        settings["commission"] = commission
        settings["min_commission"] = min_comm
        settings["slippage"] = slippage
        settings["capital"] = capital
        settings["stamp_duty"] = stamp
        settings["risk_free_rate"] = risk_free
        _save_settings(settings)
        return dbc.Alert("回测参数已保存", color="success", dismissable=True, duration=3000)

    @app.callback(
        Output("settings-save-status", "children", allow_duplicate=True),
        Input("cfg-benchmark-save-btn", "n_clicks"),
        State("cfg-benchmark-radio", "value"),
        State("cfg-benchmark-weights", "value"),
        prevent_initial_call=True,
    )
    def save_benchmark(n, benchmark, weights_str):
        settings = _load_settings()
        settings["benchmark"] = {"type": benchmark}
        if benchmark == "mixed" and weights_str:
            try:
                settings["benchmark"]["weights"] = json.loads(weights_str)
            except json.JSONDecodeError:
                return dbc.Alert("混合基准权重JSON格式错误", color="danger")
        _save_settings(settings)
        return dbc.Alert("基准配置已保存", color="success", dismissable=True, duration=3000)

    @app.callback(
        Output("cfg-benchmark-mixed-config", "style"),
        Input("cfg-benchmark-radio", "value"),
    )
    def toggle_mixed_config(benchmark):
        if benchmark == "mixed":
            return {"display": "block"}
        return {"display": "none"}

    @app.callback(
        Output("settings-save-status", "children", allow_duplicate=True),
        Input("cfg-refresh-save-btn", "n_clicks"),
        State("cfg-refresh-daily", "value"),
        State("cfg-refresh-minute", "value"),
        State("cfg-refresh-quote", "value"),
        prevent_initial_call=True,
    )
    def save_refresh(n, daily, minute, quote):
        settings = _load_settings()
        settings["refresh"] = {
            "daily_cron": daily,
            "minute_interval": minute,
            "quote_interval": quote,
        }
        _save_settings(settings)
        return dbc.Alert("刷新策略已保存", color="success", dismissable=True, duration=3000)

    @app.callback(
        Output("cfg-log-content", "children"),
        Input("cfg-log-refresh-btn", "n_clicks"),
        State("cfg-log-filter", "value"),
        prevent_initial_call=True,
    )
    def refresh_log(n, filters):
        if not filters:
            filters = ["INFO", "WARNING", "ERROR"]
        log_path = Path("logs/app.log")
        if not log_path.exists():
            return "日志文件不存在"

        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return "无法读取日志文件"

        filtered = []
        for line in lines:
            for level in filters:
                if level in line:
                    filtered.append(line)
                    break

        return "\n".join(filtered[-200:])
