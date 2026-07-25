import io
import logging

from dash import Input, Output, State, callback, no_update, html, dcc, dash_table
import dash_bootstrap_components as dbc

from fisher.dash_app.services import get_data_service

logger = logging.getLogger(__name__)


def register_data_export_callbacks(app):
    @app.callback(
        Output("download-data", "data"),
        Input("export-data-btn", "n_clicks"),
        State("export-format-dropdown", "value"),
        State("export-symbol-input", "value"),
        State("export-start-date", "value"),
        State("export-end-date", "value"),
        prevent_initial_call=True,
    )
    def export_data(n_clicks, fmt, symbols, start_date, end_date):
        svc = get_data_service()
        try:
            rows = svc.get_cached_table(market_filter="all")
        except Exception as e:
            logger.error("Export failed: %s", e)
            return None

        if not rows:
            return None

        import polars as pl
        df = pl.DataFrame(rows)

        if symbols and symbols.strip():
            sym_list = [s.strip() for s in symbols.replace("\n", ",").split(",") if s.strip()]
            if sym_list:
                df = df.filter(pl.col("ticker").is_in(sym_list))

        if start_date:
            df = df.filter(pl.col("start_date") >= start_date)

        if end_date:
            df = df.filter(pl.col("end_date") <= end_date)

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

        svc = get_data_service()
        try:
            rows = svc.get_cached_table(text_filter=symbol.strip())
        except Exception:
            return html.Div("查询失败", className="text-danger")

        try:
            db = svc._db
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
                columns=columns, data=data[:20], page_size=10,
                style_table={"overflowX": "auto"},
                style_cell={"padding": "4px", "fontSize": "12px"},
                style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
            ),
            html.Small(f"共 {len(df)} 条记录" if len(df) > 20 else "", className="text-muted"),
        ])
