import asyncio
import io
import threading
import dash
from dash import Input, Output, State, callback, no_update, dcc, html, dash_table
import dash_bootstrap_components as dbc
import polars as pl
from datetime import date, timedelta

from fisher.store.engine import DuckDBManager
from fisher.store.schema import init_schema
from fisher.market.rate_limiter import get_global_limiter
from fisher.config.schemas import MarketConfig
from fisher.market.gateway import GatewayFactory


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

        try:
            import akshare as ak
            limiter = get_global_limiter()
            limiter.acquire()
            result_df = ak.stock_info_a_code_name()
            if result_df is None or len(result_df) == 0:
                return [], None, "未找到结果"

            q = query.strip().upper()
            matches = []
            for _, row in result_df.iterrows():
                code = str(row.get("code", ""))
                name = str(row.get("name", ""))
                if q in code or q.lower() in name.lower():
                    matches.append({
                        "label": f"{code} - {name}",
                        "value": f"{code}.UNKNOWN",
                    })

            if not matches:
                return [], None, "未找到结果"

            matches = matches[:20]
            return matches, None, f"找到 {len(matches)} 个结果"
        except Exception as e:
            return [], None, f"搜索异常: {str(e)}"

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

        db_path = "./data/fisherquant.db"
        db = DuckDBManager()

        try:
            db.connect(db_path, read_pool_size=4)
        except Exception:
            pass

        try:
            init_schema_from_path(db_path)
        except Exception:
            pass

        total = len(symbols)
        results = []
        errors = []

        for i, symbol in enumerate(symbols):
            progress = int((i / total) * 100)
            try:
                bars = _fetch_bars_sync(symbol, start_date, end_date)
                if bars:
                    _store_bars(db, symbol, bars)
                    results.append(f"✓ {symbol}: {len(bars)}条记录")
                else:
                    errors.append(f"✗ {symbol}: 无数据")
            except Exception as e:
                errors.append(f"✗ {symbol}: {str(e)[:80]}")

        final_progress = 100
        status_lines = results + errors
        status_el = html.Div([html.P(line) for line in status_lines[:20]])

        fetch_list_items = [html.Div(s) for s in symbols[:10]]
        if len(symbols) > 10:
            fetch_list_items.append(html.Small(f"...及其他 {len(symbols)-10} 个标的"))

        return final_progress, "100%", status_el, html.Div(fetch_list_items)

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
                import akshare as ak
                get_global_limiter().acquire()
                df = ak.stock_financial_abstract(symbol=symbol.strip())
                if df is None or len(df) == 0:
                    return True, html.Div("未查询到财务数据", className="text-warning")
                columns = [{"name": c, "id": c} for c in df.columns]
                data = df.to_dict("records")
                return True, dash_table.DataTable(
                    columns=columns,
                    data=data,
                    page_size=15,
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

    @app.callback(
        Output("download-data", "data"),
        Input("export-data-btn", "n_clicks"),
        State("export-format-dropdown", "value"),
        prevent_initial_call=True,
    )
    def export_data(n_clicks, fmt):
        db = _get_db()
        try:
            df = db.query_df("SELECT * FROM bars_daily ORDER BY ticker, trade_date")
        except Exception:
            return None

        if len(df) == 0:
            return None

        import io
        if fmt == "csv":
            buf = io.StringIO()
            df.write_csv(buf)
            buf.seek(0)
            return dcc.send_string(buf.getvalue(), filename="fisherquant_data.csv")
        elif fmt == "xlsx":
            buf = io.BytesIO()
            df.write_excel(buf)
            buf.seek(0)
            return dcc.send_bytes(buf.getvalue(), filename="fisherquant_data.xlsx")
        elif fmt == "parquet":
            buf = io.BytesIO()
            df.write_parquet(buf)
            buf.seek(0)
            return dcc.send_bytes(buf.getvalue(), filename="fisherquant_data.parquet")
        return None

    @app.callback(
        Output("adj-factor-result", "children"),
        Input("fetch-adj-factor-btn", "n_clicks"),
        State("adj-factor-symbol", "value"),
        prevent_initial_call=True,
    )
    def fetch_adj_factor(n_clicks, symbol):
        if not symbol or not symbol.strip():
            return html.Div("请输入标的代码", className="text-warning")

        db = _get_db()
        try:
            df = db.query_df(
                "SELECT trade_date, adj_factor FROM bars_daily WHERE ticker=? ORDER BY trade_date",
                [symbol.strip()],
            )
        except Exception:
            return html.Div("查询失败", className="text-danger")

        if len(df) == 0:
            return html.Div("未找到该标的的数据", className="text-warning")

        has_adj = (df["adj_factor"] != 1.0).any()
        badge = dbc.Badge("已复权", color="success", className="ms-2") if has_adj else dbc.Badge("未复权", color="secondary", className="ms-2")

        columns = [
            {"name": "日期", "id": "trade_date"},
            {"name": "复权因子", "id": "adj_factor"},
        ]
        data = df.to_dicts()
        return html.Div([
            html.Div([html.Strong(f"标的: {symbol.strip()}"), badge], className="mb-2"),
            dash_table.DataTable(
                columns=columns,
                data=data[:20],
                page_size=10,
                style_table={"overflowX": "auto"},
                style_cell={"padding": "4px", "fontSize": "12px"},
                style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
            ),
            html.Small(f"共 {len(df)} 条记录" if len(df) > 20 else "", className="text-muted"),
        ])

    @app.callback(
        Output("cached-table-container", "children", allow_duplicate=True),
        Input("cache-refresh-btn", "n_clicks"),
        State("data-center-tabs", "active_tab"),
        prevent_initial_call=True,
    )
    def force_refresh_cached(n, active_tab):
        if active_tab != "tab-cached":
            return no_update
        db = _get_db()
        return _build_cached_table(db)

    @app.callback(
        Output("cached-table-container", "children"),
        Input("data-center-tabs", "active_tab"),
        Input("cache-market-filter", "value"),
        Input("cache-filter-input", "value"),
        Input("cache-refresh-btn", "n_clicks"),
        Input("cache-delete-btn", "n_clicks"),
    )
    def render_cached_table(active_tab, market_filter, filter_text, refresh_clicks, delete_clicks):
        if active_tab != "tab-cached":
            return no_update

        db = _get_db()
        where_clauses = []
        params = []

        if market_filter and market_filter != "all":
            where_clauses.append("market = ?")
            params.append(market_filter)

        if filter_text and filter_text.strip():
            where_clauses.append("(ticker LIKE ? OR ticker LIKE ?)")
            f = f"%{filter_text.strip()}%"
            params.extend([f, f])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT ticker, market,
                   COUNT(*) AS records,
                   MIN(trade_date) AS start_date,
                   MAX(trade_date) AS end_date
            FROM bars_daily
            {where_sql}
            GROUP BY ticker, market
            ORDER BY ticker
        """
        try:
            df = db.query_df(sql, params)
        except Exception:
            return _empty_cached_table()

        if len(df) == 0:
            return _empty_cached_table()

        columns = [
            {"name": "代码", "id": "ticker"},
            {"name": "市场", "id": "market"},
            {"name": "数据条数", "id": "records"},
            {"name": "起始日期", "id": "start_date"},
            {"name": "最新日期", "id": "end_date"},
        ]

        data = df.to_dicts()
        return dash_table.DataTable(
            id="cached-data-table",
            columns=columns,
            data=data,
            row_selectable="multi",
            page_size=10,
            style_table={"overflowX": "auto"},
            style_cell={
                "padding": "8px",
                "fontSize": "13px",
            },
            style_header={
                "backgroundColor": "#f8f9fa",
                "fontWeight": "bold",
            },
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
            ],
        )

    @app.callback(
        Output("cached-table-container", "children", allow_duplicate=True),
        Input("cache-delete-btn", "n_clicks"),
        State("cached-data-table", "selected_rows"),
        State("cached-data-table", "data"),
        prevent_initial_call=True,
    )
    def delete_selected_rows(n_clicks, selected_rows, table_data):
        if not selected_rows or not table_data:
            return no_update

        db = _get_db()
        for idx in selected_rows:
            row = table_data[idx]
            ticker = row["ticker"]
            try:
                db.execute("DELETE FROM bars_daily WHERE ticker = ?", [ticker])
                db.execute("DELETE FROM bars_minute WHERE ticker = ?", [ticker])
                db.execute("DELETE FROM corporate_actions WHERE ticker = ?", [ticker])
            except Exception:
                continue

        return _build_cached_table(db)


def _get_db():
    db_path = "./data/fisherquant.db"
    db = DuckDBManager()
    try:
        db.connect(db_path, read_pool_size=4)
        init_schema_from_path(db_path)
    except Exception:
        pass
    return db


def _build_cached_table(db):
    try:
        df = db.query_df("""
            SELECT ticker, market,
                   COUNT(*) AS records,
                   MIN(trade_date) AS start_date,
                   MAX(trade_date) AS end_date
            FROM bars_daily
            GROUP BY ticker, market
            ORDER BY ticker
        """)
    except Exception:
        return _empty_cached_table()

    if len(df) == 0:
        return _empty_cached_table()

    columns = [
        {"name": "代码", "id": "ticker"},
        {"name": "市场", "id": "market"},
        {"name": "数据条数", "id": "records"},
        {"name": "起始日期", "id": "start_date"},
        {"name": "最新日期", "id": "end_date"},
    ]
    return dash_table.DataTable(
        id="cached-data-table",
        columns=columns,
        data=df.to_dicts(),
        row_selectable="multi",
        page_size=10,
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontSize": "13px"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
        ],
    )


def _empty_cached_table():
    return html.Div(
        [
            html.H5("暂无缓存数据", className="text-muted text-center mt-4"),
            html.P('请先在"数据查询"标签页中搜索并获取数据', className="text-muted text-center"),
        ]
    )


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


def _fetch_bars_sync(symbol, start_date, end_date):
    adapter = _get_adapter()
    bars = _run_async(adapter.get_bars(symbol, start_date, end_date))
    return bars


def _store_bars(db, symbol, bars):
    core_columns = ["ticker", "trade_date", "market", "open", "high", "low", "close", "volume", "amount"]
    rows = []
    for b in bars:
        d = b.to_dict()
        rows.append({
            "ticker": d.get("ticker", symbol),
            "trade_date": d.get("trade_date", ""),
            "market": d.get("market", "a_share"),
            "open": float(d.get("open", 0)),
            "high": float(d.get("high", 0)),
            "low": float(d.get("low", 0)),
            "close": float(d.get("close", 0)),
            "volume": int(d.get("volume", 0)),
            "amount": float(d.get("amount", 0)),
        })
    if not rows:
        return

    df = pl.DataFrame(rows)
    db.execute_many(
        """INSERT OR REPLACE INTO bars_daily
           (ticker, trade_date, open, high, low, close, volume, amount, market)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            [r["ticker"], r["trade_date"], r["open"], r["high"], r["low"],
             r["close"], r["volume"], r["amount"], r["market"]]
            for r in rows
        ],
    )


def init_schema_from_path(db_path):
    from fisher.store.engine import DuckDBEngine
    engine = DuckDBEngine(db_path)
    init_schema(engine)
    engine.close()
