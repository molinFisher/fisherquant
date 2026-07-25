from dash import Input, Output, callback
from dash import html
import dash_bootstrap_components as dbc
from fisher.store.engine import DuckDBManager


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
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

        try:
            db = DuckDBManager()
            if not db._initialized:
                return "暂无数据", "0", "0", "0", "0", "最近更新: -"
        except Exception:
            return "暂无数据", "0", "0", "0", "0", "最近更新: -"

        try:
            tickers_df = db.query_df("SELECT COUNT(DISTINCT ticker) AS cnt FROM bars_daily")
            total_tickers = str(tickers_df["cnt"][0]) if len(tickers_df) > 0 else "0"
        except Exception:
            total_tickers = "0"

        try:
            ashare_df = db.query_df("SELECT COUNT(DISTINCT ticker) AS cnt FROM bars_daily WHERE market='a_share'")
            ashare = str(ashare_df["cnt"][0]) if len(ashare_df) > 0 else "0"
        except Exception:
            ashare = "0"

        try:
            hk_df = db.query_df("SELECT COUNT(DISTINCT ticker) AS cnt FROM bars_daily WHERE market='hk_connect'")
            hk = str(hk_df["cnt"][0]) if len(hk_df) > 0 else "0"
        except Exception:
            hk = "0"

        try:
            records_df = db.query_df("SELECT COUNT(*) AS cnt FROM bars_daily")
            records = str(records_df["cnt"][0]) if len(records_df) > 0 else "0"
        except Exception:
            records = "0"

        try:
            latest_df = db.query_df("SELECT MAX(trade_date) AS dt FROM bars_daily")
            if len(latest_df) > 0 and latest_df["dt"][0] is not None:
                last_update = f"最近更新: {latest_df['dt'][0]}"
            else:
                last_update = "最近更新: -"
        except Exception:
            last_update = "最近更新: -"

        recent_backtests_section = _build_recent_backtests(db)

        return (
            recent_backtests_section,
            total_tickers,
            ashare,
            hk,
            records,
            last_update,
        )

    @app.callback(
        Output("quick-fetch", "n_clicks"),
        Output("quick-strategy", "n_clicks"),
        Output("quick-backtest", "n_clicks"),
        Input("url", "pathname"),
        prevent_initial_call=True,
    )
    def quick_action_handler(pathname):
        raise dash.exceptions.PreventUpdate


def _build_recent_backtests(db):
    try:
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
    except Exception:
        return "暂无回测记录"
