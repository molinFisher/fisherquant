import asyncio
import threading
from dash import Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
from dash import html, dcc
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
