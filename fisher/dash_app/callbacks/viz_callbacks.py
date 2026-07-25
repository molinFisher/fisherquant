from urllib.parse import parse_qs, urlparse
from pathlib import Path

import dash
from dash import Input, Output, State, callback, no_update, html, dcc
import dash_bootstrap_components as dbc
import polars as pl

from fisher.backtest.serializer import BacktestSerializer
from fisher.visualization.downsample import lttb
from fisher.analytics.performance import daily_returns, max_drawdown
from fisher.dash_app.pages.visual_dashboard import (
    _build_equity_chart,
    _build_drawdown_chart,
    _build_monthly_heatmap,
    _build_return_histogram,
    _build_trade_log,
    _build_kline_chart,
)
from fisher.store.engine import DuckDBManager


def register_viz_callbacks(app):
    @app.callback(
        Output("viz-backtest-id", "data"),
        Output("viz-backtest-data", "data"),
        Output("viz-loading-container", "children"),
        Output("viz-content", "style"),
        Input("viz-url", "search"),
    )
    def load_backtest_from_url(search):
        if not search:
            return None, None, "请输入回测ID或在回测中心点击"查看完整看板"", {"display": "none"}

        params = parse_qs(search.lstrip("?"))
        backtest_id = params.get("backtest_id", [None])[0]
        if not backtest_id:
            return None, None, "请输入回测ID或在回测中心点击"查看完整看板"", {"display": "none"}

        try:
            serializer = BacktestSerializer()
            data = serializer.load(backtest_id)
        except Exception:
            return None, None, f"加载回测 {backtest_id} 失败", {"display": "none"}

        if not data or "equity" not in data:
            return None, None, f"回测 {backtest_id} 无数据", {"display": "none"}

        result = {
            "id": backtest_id,
            "equity": data.get("equity", []),
            "benchmark": data.get("benchmark", []),
            "trades": data.get("trades", []),
            "metadata": data.get("metadata", {}),
        }
        return backtest_id, result, html.Div(), {"display": "block"}

    @app.callback(
        Output("viz-equity-chart", "children"),
        Input("viz-tabs", "active_tab"),
        State("viz-backtest-data", "data"),
    )
    def render_equity(active_tab, backtest_data):
        if active_tab != "tab-equity" or not backtest_data:
            return no_update
        nav = backtest_data.get("equity", [])
        bench = backtest_data.get("benchmark", [])
        if not nav:
            return html.Div("无净值数据", className="text-muted")
        return _build_equity_chart(nav, bench)

    @app.callback(
        Output("viz-drawdown-chart", "children"),
        Input("viz-tabs", "active_tab"),
        State("viz-backtest-data", "data"),
    )
    def render_drawdown(active_tab, backtest_data):
        if active_tab != "tab-drawdown" or not backtest_data:
            return no_update
        nav = backtest_data.get("equity", [])
        if not nav:
            return html.Div("无净值数据", className="text-muted")
        return _build_drawdown_chart(nav)

    @app.callback(
        Output("viz-monthly-heatmap", "children"),
        Input("viz-tabs", "active_tab"),
        State("viz-backtest-data", "data"),
    )
    def render_heatmap(active_tab, backtest_data):
        if active_tab != "tab-heatmap" or not backtest_data:
            return no_update
        nav = backtest_data.get("equity", [])
        if not nav:
            return html.Div("无净值数据", className="text-muted")
        rets = daily_returns(nav)
        return _build_monthly_heatmap(rets)

    @app.callback(
        Output("viz-return-histogram", "children"),
        Input("viz-tabs", "active_tab"),
        State("viz-backtest-data", "data"),
    )
    def render_histogram(active_tab, backtest_data):
        if active_tab != "tab-histogram" or not backtest_data:
            return no_update
        nav = backtest_data.get("equity", [])
        if not nav:
            return html.Div("无净值数据", className="text-muted")
        rets = daily_returns(nav)
        return _build_return_histogram(rets)

    @app.callback(
        Output("viz-trade-log", "children"),
        Input("viz-tabs", "active_tab"),
        State("viz-backtest-data", "data"),
    )
    def render_trades(active_tab, backtest_data):
        if active_tab != "tab-trades" or not backtest_data:
            return no_update
        trades = backtest_data.get("trades", [])
        return _build_trade_log(trades)

    @app.callback(
        Output("viz-kline-symbol", "options"),
        Input("viz-backtest-data", "data"),
    )
    def load_kline_symbols(backtest_data):
        if not backtest_data:
            return []
        metadata = backtest_data.get("metadata", {})
        symbols_list = metadata.get("symbols", [])
        return [{"label": s, "value": s} for s in symbols_list]

    @app.callback(
        Output("viz-kline-chart", "children"),
        Input("viz-tabs", "active_tab"),
        Input("viz-kline-symbol", "value"),
        State("viz-backtest-data", "data"),
    )
    def render_kline(active_tab, symbol, backtest_data):
        if active_tab != "tab-kline" or not backtest_data:
            return no_update
        if not symbol or not backtest_data:
            return html.Div("请先选择标的", className="text-muted")

        metadata = backtest_data.get("metadata", {})
        start_date = metadata.get("start_date", "2024-01-01")
        end_date = metadata.get("end_date", "2025-06-30")

        try:
            db = DuckDBManager()
            if not db._initialized:
                try:
                    db.connect("./data/fisherquant.db", read_pool_size=4)
                except Exception:
                    pass
            df = db.query_df(
                "SELECT ticker, trade_date, open, high, low, close, volume, amount, market "
                "FROM bars_daily WHERE ticker=? AND trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date",
                [symbol, start_date, end_date],
            )
        except Exception:
            return html.Div("无法加载K线数据", className="text-danger")

        if len(df) == 0:
            return html.Div(f"无标的 {symbol} 的数据", className="text-danger")

        trades = backtest_data.get("trades", [])
        symbol_trades = [t for t in trades if t.get("ticker") == symbol]

        return _build_kline_chart(df, symbol_trades, symbol)
