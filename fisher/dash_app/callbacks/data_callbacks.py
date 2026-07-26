import dash
from dash import Input, Output, State, no_update, html
import dash_bootstrap_components as dbc


def register_data_callbacks(app):
    from fisher.dash_app.services import get_data_service

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

        try:
            svc = get_data_service()
            matches = svc.search_symbols(query.strip())
            if not matches:
                return [], None, "未找到结果"
            return matches, None, f"找到 {len(matches)} 个结果"
        except Exception as e:
            return [], None, f"搜索异常: {str(e)}"

    @app.callback(
        Output("fetch-status", "children"),
        Output("fetch-list", "children"),
        Output("fetch-progress-status", "data"),
        Input("fetch-data-button", "n_clicks"),
        State("symbol-search-results", "value"),
        State("batch-symbols-input", "value"),
        State("date-range-picker", "start_date"),
        State("date-range-picker", "end_date"),
        State("data-type-radio", "value"),
        State("minute-period-selector", "value"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("fetch-data-button", "disabled"), True, False),
            (Output("fetch-data-button", "children"), "获取中...", "开始获取数据"),
        ],
    )
    def fetch_data(n_clicks, selected_symbol, batch_input, start_date, end_date,
                   data_type, minute_period):
        symbols = []
        if batch_input and batch_input.strip():
            parts = batch_input.strip().replace("\n", ",").split(",")
            for p in parts:
                p = p.strip()
                if p:
                    symbols.append(p)
        if selected_symbol and selected_symbol not in symbols:
            symbols.append(selected_symbol)
        symbols = symbols[:20]

        if not symbols:
            return "请先选择或输入标的", "请先搜索并选择标的", {}

        svc = get_data_service()
        total = len(symbols)
        results = []
        errors = []

        for i, symbol in enumerate(symbols):
            period = minute_period.replace("min", "") if minute_period else ""
            try:
                result = svc.fetch_bars([symbol], start_date, end_date, data_type, period)
                sym_result = result.get(symbol, {})
                if sym_result.get("status") == "ok":
                    count = sym_result.get("count", 0)
                    if count:
                        results.append(f"✓ {symbol}: {count}条记录")
                    else:
                        results.append(f"✓ {symbol}: 财务数据已获取")
                else:
                    errors.append(f"✗ {symbol}: {sym_result.get('error', '无数据')}")
            except Exception as e:
                errors.append(f"✗ {symbol}: {str(e)[:80]}")

            yield dash.no_update, dash.no_update, {
                "current": i + 1, "total": total, "symbol": symbol,
            }

        status_lines = results + errors
        status_el = html.Div([html.P(line) for line in status_lines[:20]])
        fetch_list_items = [html.Div(s) for s in symbols[:10]]
        if len(symbols) > 10:
            fetch_list_items.append(html.Small(f"...及其他 {len(symbols)-10} 个标的"))
        return status_el, html.Div(fetch_list_items), {
            "current": total, "total": total,
        }

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
        Output("financials-modal", "is_open", allow_duplicate=True),
        Input("close-financials-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_modal(n):
        return False



