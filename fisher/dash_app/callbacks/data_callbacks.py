import asyncio
from dash import Input, Output, State, callback, no_update, html, dcc, dash_table
import dash_bootstrap_components as dbc
import akshare as ak

from fisher.dash_app.services import get_data_service, get_limiter
from fisher.market.gateway import GatewayFactory
from fisher.config.schemas import MarketConfig


def _get_adapter():
    cfg = MarketConfig()
    return GatewayFactory.create(cfg)


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def register_data_callbacks(app):
    @app.callback(
        Output("symbol-search-results", "options"),
        Output("symbol-search-results", "value"),
        Output("search-status", "children"),
        Input("symbol-search-input", "value"),
        prevent_initial_call=True,
    )
    def search_symbols(query):
        if not query or len(query.strip()) < 2:
            return [], None, ""

        svc = get_data_service()
        results = svc.search_symbols(query.strip())
        if not results:
            return [], None, "未找到结果"
        return results, None, f"找到 {len(results)} 个结果"

    @app.callback(
        Output("fetch-progress-bar", "value"),
        Output("fetch-progress-bar", "label"),
        Output("fetch-status", "children"),
        Output("fetch-list", "children"),
        Input("fetch-data-button", "n_clicks"),
        State("symbol-search-results", "value"),
        State("batch-symbols-input", "value"),
        State("date-range-picker", "start_date"),
        State("date-range-picker", "end_date"),
        State("data-type-radio", "value"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("fetch-data-button", "disabled"), True, False),
            (Output("fetch-data-button", "children"), "获取中...", "开始获取数据"),
        ],
    )
    def fetch_data(n_clicks, selected_symbol, batch_input, start_date, end_date, data_type):
        symbols = _resolve_symbols(selected_symbol, batch_input)
        if not symbols:
            return 0, "0%", "请先选择或输入标的", "请先搜索并选择标的"

        svc = get_data_service()
        results = svc.fetch_bars(symbols, start_date, end_date, data_type or "daily")

        status_lines = []
        for sym, info in results.items():
            if info["status"] == "ok":
                status_lines.append(f"{sym}: {info.get('count', 0)}条记录")
            else:
                status_lines.append(f"{sym}: {info.get('error', '无数据')}")

        status_el = html.Div([html.P(line) for line in status_lines[:20]])
        fetch_list_items = [html.Div(s) for s in symbols[:10]]
        if len(symbols) > 10:
            fetch_list_items.append(html.Small(f"...及其他 {len(symbols)-10} 个标的"))
        return 100, "100%", status_el, html.Div(fetch_list_items)

    @app.callback(
        Output("fetch-list", "children", allow_duplicate=True),
        Input("symbol-search-results", "value"),
        prevent_initial_call=True,
    )
    def update_fetch_list(selected_symbol):
        if not selected_symbol:
            return "请先搜索并选择标的"
        return html.Div([
            html.Strong("已选择: "),
            html.Span(str(selected_symbol)),
        ])

    @app.callback(
        Output("symbol-search-results", "value", allow_duplicate=True),
        Input("batch-symbols-input", "value"),
        prevent_initial_call=True,
    )
    def clear_single_search_on_batch(batch_input):
        if batch_input and batch_input.strip():
            return None
        return no_update

    @app.callback(
        Output("minute-period-container", "style"),
        Input("data-type-radio", "value"),
    )
    def toggle_minute_period(data_type):
        if data_type == "minute":
            return {"display": "block"}
        return {"display": "none"}

    @app.callback(
        Output("financials-modal", "is_open"),
        Output("financials-modal-body", "children"),
        Input("query-financials-btn", "n_clicks"),
        Input("close-financials-modal", "n_clicks"),
        State("financials-symbol-input", "value"),
        State("financials-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_financials_modal(query_clicks, close_clicks, symbol, is_open):
        ctx = dash.callback_context
        if not ctx.triggered:
            return False, ""
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id == "close-financials-modal":
            return False, ""

        if trigger_id == "query-financials-btn":
            if not symbol or not symbol.strip():
                return True, html.Div("请输入标的代码", className="text-danger")
            try:
                get_limiter().acquire()
                df = ak.stock_financial_abstract(symbol=symbol.strip())
                if df is None or len(df) == 0:
                    return True, html.Div("未查询到财务数据", className="text-warning")
                columns = [{"name": c, "id": c} for c in df.columns]
                data = df.to_dict("records")
                return True, dash_table.DataTable(
                    columns=columns, data=data, page_size=15,
                    style_table={"overflowX": "auto"},
                    style_cell={"padding": "6px", "fontSize": "12px"},
                    style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
                )
            except Exception as e:
                return True, html.Div(f"查询失败: {str(e)}", className="text-danger")

        return False, ""

    @app.callback(
        Output("financials-modal", "is_open", allow_duplicate=True),
        Input("close-financials-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_modal(n):
        return False

    @app.callback(
        Output("next-refresh-time", "children"),
        Input("auto-refresh-toggle", "value"),
        Input("auto-refresh-cron", "value"),
    )
    def update_next_refresh_time(enabled, cron_expr):
        if not enabled:
            return ""
        if not cron_expr:
            return "请输入cron表达式"
        try:
            from apscheduler.triggers.cron import CronTrigger
            from datetime import datetime
            trigger = CronTrigger.from_crontab(cron_expr)
            now = datetime.now()
            next_run = trigger.get_next_fire_time(None, now)
            if next_run:
                return f"下次刷新: {next_run.strftime('%Y-%m-%d %H:%M:%S')}"
            return "cron表达式无效"
        except Exception:
            return "cron表达式格式错误"


def _resolve_symbols(selected_symbol, batch_input):
    symbols = []
    if batch_input and batch_input.strip():
        parts = batch_input.strip().replace("\n", ",").split(",")
        for p in parts:
            p = p.strip()
            if p:
                symbols.append(p)
    if selected_symbol and selected_symbol not in symbols:
        symbols.append(selected_symbol)
    return symbols[:20]
