import logging
import dash
from dash import Input, Output, State, no_update, html
import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)


def register_data_callbacks(app):
    from fisher.dash_app.services import get_data_service

    @app.callback(
        Output("symbol-search-results", "options"),
        Output("symbol-search-results", "value"),
        Output("search-status", "children"),
        Output("search-results-store", "data"),
        Input("symbol-search-input", "value"),
        prevent_initial_call=True,
    )
    def search_symbols(query):
        # R-31 三态一：输入不足
        if not query or len(query.strip()) < 2:
            return [], None, html.Span("请输入至少 2 个字符", className="text-muted"), []

        try:
            svc = get_data_service()
            matches = svc.search_symbols(query.strip())
        except Exception:
            # R-31：不向用户暴露技术堆栈，仅给出友好提示（技术细节已在服务层落日志）
            logger.exception("search_symbols callback failed")
            return [], None, html.Span("搜索服务暂时不可用，请稍后重试", className="text-danger"), []

        # R-31 三态二：无结果
        if not matches:
            # R-02 冷启动：字典为空表示后台初始化未完成，给出"初始化中"提示而非"未找到"
            try:
                if not svc.symbol_dict_ready():
                    return [], None, html.Span(
                        "标的列表初始化中，请稍候…", className="text-info"), []
            except Exception:
                logger.debug("symbol_dict_ready 检查失败，回退无结果提示")
            return [], None, html.Span(
                "未找到匹配的标的，试试代码、名称或拼音", className="text-warning"), []

        # R-31 三态三：有结果 —— 统计条（总数 + 市场分布）
        options = [{"label": m["label"], "value": m["value"]} for m in matches]
        a_n = sum(1 for m in matches if m.get("market") == "a_share")
        hk_n = len(matches) - a_n
        status = html.Span(
            [
                html.Span(f"找到 {len(matches)} 个结果", className="text-success me-2"),
                html.Small(f"A股 {a_n} · 港股 {hk_n}", className="text-muted"),
            ]
        )
        return options, None, status, matches

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
        State("search-results-store", "data"),
        prevent_initial_call=True,
    )
    def update_fetch_list(selected_symbol, results):
        # R-32：选中后回填富信息卡片（代码 / 名称 / 市场 / 拼音）
        if not selected_symbol:
            return "请先搜索并选择标的"
        item = None
        for r in results or []:
            if r.get("value") == selected_symbol:
                item = r
                break
        if not item:
            return html.Div([html.Strong("已选择："), html.Span(str(selected_symbol))])

        market_tag = "A股" if item.get("market") == "a_share" else "港股"
        badge_color = "danger" if item.get("market") == "a_share" else "info"
        abbr = (item.get("pinyin_abbr") or "").strip()
        header = [
            dbc.Badge(market_tag, color=badge_color, className="me-2"),
            html.Strong(item.get("name", "")),
        ]
        meta = [html.Span(f"代码 {item.get('code', '')}", className="me-3"),
                html.Span(f"标准代码 {selected_symbol}", className="text-muted")]
        if abbr:
            meta.append(html.Span(f" · 拼音 {abbr}", className="text-muted ms-2"))
        return dbc.Card(
            dbc.CardBody([
                html.Div(header, className="mb-1"),
                html.Div(meta, className="small"),
            ]),
            className="border-primary",
        )

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



