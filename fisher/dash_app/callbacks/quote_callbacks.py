import dash
from dash import Input, Output, State, callback, no_update, html, ctx
import dash_bootstrap_components as dbc

from fisher.store.engine import DuckDBManager


QB_WATCHLIST_FILE = "data/watchlist.json"


def _get_cached_symbols():
    try:
        db = DuckDBManager()
        if not db._initialized:
            try:
                db.connect("./data/fisherquant.db", read_pool_size=4)
            except Exception:
                pass
        df = db.query_df("SELECT DISTINCT ticker FROM bars_daily ORDER BY ticker")
        return [{"label": r[0], "value": r[0]} for r in df.iter_rows()]
    except Exception:
        return []


def _load_watchlist():
    import json
    from pathlib import Path
    try:
        return json.loads(Path(QB_WATCHLIST_FILE).read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_watchlist(items):
    import json
    from pathlib import Path
    Path(QB_WATCHLIST_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(QB_WATCHLIST_FILE).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def register_quote_callbacks(app):
    @app.callback(
        Output("qb-add-symbol-dropdown", "options"),
        Input("url", "pathname"),
    )
    def load_qb_symbols(pathname):
        return _get_cached_symbols()

    @app.callback(
        Output("qb-watchlist-store", "data"),
        Output("qb-table-container", "children"),
        Input("qb-add-btn", "n_clicks"),
        Input("qb-manual-refresh", "n_clicks"),
        Input("qb-refresh-interval", "n_intervals"),
        State("qb-add-symbol-dropdown", "value"),
        State("qb-watchlist-store", "data"),
    )
    def update_watchlist(add_clicks, refresh_clicks, auto_interval, new_symbol, watchlist):
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        watchlist = watchlist or []
        if triggered_id == "qb-add-btn" and new_symbol:
            if new_symbol not in watchlist:
                watchlist.append(new_symbol)
            _save_watchlist(watchlist)

        if not watchlist:
            watchlist = _load_watchlist()
        if not watchlist:
            return watchlist, html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4")

        table_data = _fetch_quote_data(watchlist)
        return watchlist, _build_quote_table(table_data)

    @app.callback(
        Output("qb-refresh-interval", "disabled"),
        Input("qb-auto-refresh-toggle", "value"),
    )
    def toggle_auto_refresh(enabled):
        return not enabled

    @app.callback(
        Output("qb-trading-status", "data"),
        Input("url", "pathname"),
    )
    def check_trading_hours(pathname):
        import datetime
        now = datetime.datetime.now()
        weekday = now.weekday()
        if weekday >= 5:
            return False
        hour = now.hour
        minute = now.minute
        # 盘前：9:15 之前休市
        if hour < 9 or (hour == 9 and minute < 15):
            return False
        # 午休：11:30 - 13:00 休市（A 股连续交易上午 11:30 结束，下午 13:00 重开）
        if (hour == 11 and minute >= 30) or hour == 12:
            return False
        # 收盘：15:00 之后休市
        if hour >= 15:
            return False
        return True


def _fetch_quote_data(symbols):
    data = []
    try:
        db = DuckDBManager()
        if not db._initialized:
            try:
                db.connect("./data/fisherquant.db", read_pool_size=4)
            except Exception:
                pass
        for sym in symbols:
            try:
                df = db.query_df(
                    "SELECT close, volume, trade_date FROM bars_daily WHERE ticker=? "
                    "ORDER BY trade_date DESC LIMIT 2",
                    [sym],
                )
                if len(df) >= 2:
                    last_close = df["close"][0]
                    prev_close = df["close"][1]
                    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close and prev_close > 0 else 0
                    volume = df["volume"][0]
                    data.append({
                        "code": sym,
                        "name": sym.split(".")[0],
                        "last_price": f"{last_close:.2f}",
                        "change_pct": f"{change_pct:+.2f}%",
                        "volume": f"{volume:,}",
                        "change_raw": change_pct,
                    })
            except Exception:
                data.append({
                    "code": sym, "name": sym.split(".")[0],
                    "last_price": "-", "change_pct": "-", "volume": "-",
                    "change_raw": 0,
                })
    except Exception:
        pass
    return data


def _build_quote_table(data):
    from dash import dash_table
    columns = [
        {"name": "代码", "id": "code"},
        {"name": "名称", "id": "name"},
        {"name": "最新价", "id": "last_price"},
        {"name": "涨跌幅", "id": "change_pct"},
        {"name": "成交量", "id": "volume"},
    ]
    return dash_table.DataTable(
        id="qb-data-table",
        columns=columns,
        data=data,
        page_size=15,
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontSize": "13px"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": "{change_raw} > 0", "column_id": "change_pct"},
             "color": "#dc3545"},
            {"if": {"filter_query": "{change_raw} < 0", "column_id": "change_pct"},
             "color": "#198754"},
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
        ],
    )
