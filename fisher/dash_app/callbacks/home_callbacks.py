import logging

import dash
from dash import Input, Output, callback, no_update
from dash import html, dcc
import dash_bootstrap_components as dbc
from fisher.dash_app.services import get_data_service, get_auto_load_service
from fisher.store.engine import DuckDBManager

logger = logging.getLogger(__name__)


def register_home_callbacks(app):
    @app.callback(
        Output("recent-backtests", "children"),
        Output("stat-tickers-count", "children"),
        Output("stat-ashare-count", "children"),
        Output("stat-hk-count", "children"),
        Output("stat-records-count", "children"),
        Output("stat-last-update", "children"),
        Input("url", "pathname"),
    )
    def update_home_dashboard(pathname):
        if pathname not in (None, "/", "/home"):
            return no_update, no_update, no_update, no_update, no_update, no_update

        try:
            svc = get_data_service()
            stats = svc.get_cache_stats()
            total_tickers = str(stats["total"])
            ashare = str(stats["a_share"])
            hk = str(stats["hk"])
            records = str(stats["records"])
            last_update = f"最近更新: {stats['last_update']}" if stats["last_update"] else "最近更新: -"
        except Exception as e:
            logger.error("Failed to get cache stats: %s", e)
            total_tickers = "0"
            ashare = "0"
            hk = "0"
            records = "0"
            last_update = "最近更新: -"

        recent_backtests_section = _build_recent_backtests()
        return (
            recent_backtests_section,
            total_tickers,
            ashare,
            hk,
            records,
            last_update,
        )

    @app.callback(
        Output("quick-nav-location", "href"),
        Input("quick-fetch", "n_clicks"),
        Input("quick-strategy", "n_clicks"),
        Input("quick-backtest", "n_clicks"),
        prevent_initial_call=True,
    )
    def quick_action_handler(fetch_clicks, strategy_clicks, backtest_clicks):
        ctx = dash.callback_context
        if not ctx.triggered:
            return no_update
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        nav_map = {
            "quick-fetch": "/data-center",
            "quick-strategy": "/strategy-center",
            "quick-backtest": "/backtest-center",
        }
        return nav_map.get(trigger_id, "/data-center")

    @app.callback(
        Output("auto-load-indicator", "children"),
        Input("auto-load-poll", "n_intervals"),
    )
    def update_auto_load_indicator(n):
        try:
            svc = get_auto_load_service()
            progress = svc.get_progress()
        except Exception as e:
            logger.error("Auto-load progress check failed: %s", e)
            return html.Div()

        phase = progress.get("phase", "idle")
        current = progress.get("current", 0)
        total = progress.get("total", 0)

        if phase == "initial_load" and total > 0:
            return html.Div(
                dbc.Alert(
                    f"⏳ 数据加载中，已加载 {current}/{total} 只",
                    color="info", className="py-1 px-3 small mb-0",
                    style={"fontSize": "14px"},
                )
            )
        if phase in ("idle", "complete") and total > 0 and current >= total:
            return html.Div(
                dbc.Alert("✅ 数据就绪", color="success", className="py-1 px-3 small mb-0",
                          style={"fontSize": "14px"})
            )
        if phase == "error":
            return html.Div(
                dbc.Alert("⚠️ 数据加载出错", color="warning", className="py-1 px-3 small mb-0",
                          style={"fontSize": "14px"})
            )
        return html.Div()


def _build_recent_backtests():
    try:
        db = DuckDBManager()
        orders_df = db.query_df("SELECT * FROM orders ORDER BY created_at DESC LIMIT 5")
        if len(orders_df) == 0:
            return "暂无回测记录"
        items = []
        for row in orders_df.iter_rows():
            items.append(
                dbc.ListGroupItem(
                    [
                        html.Div(
                            [
                                html.Strong(f"{row[1]} "),
                                html.Span(f"{row[2]} {row[3]}股", className="text-muted"),
                            ]
                        ),
                        html.Small(f"状态: {row[6]}", className="text-muted"),
                    ]
                )
            )
        return dbc.ListGroup(items)
    except Exception as e:
        logger.error("Failed to build recent backtests: %s", e)
        return "暂无回测记录"
