import dash
from dash import Input, Output, State, callback, no_update, html, ctx, dash_table
import dash_bootstrap_components as dbc
import polars as pl

from fisher.store.engine import DuckDBManager
from fisher.factor.storage import FactorStorage
from fisher.factor.engine import FactorEngine
from fisher.factor.registry import FactorRegistry
from fisher.factor.base import Factor


def register_factor_callbacks(app):
    @app.callback(
        Output("factor-compute-symbols", "options"),
        Output("factor-preview-symbol", "options"),
        Input("factor-center-tabs", "active_tab"),
    )
    def load_cached_symbols(active_tab):
        try:
            db = _get_db()
            df = db.query_df("SELECT DISTINCT ticker FROM bars_daily ORDER BY ticker")
            options = [{"label": r[0], "value": r[0]} for r in df.iter_rows()]
        except Exception:
            options = []
        return options, options

    @app.callback(
        Output("factor-compute-symbol-count", "children"),
        Input("factor-compute-symbols", "value"),
    )
    def update_symbol_count(symbols):
        if not symbols:
            return "未选择标的"
        return f"已选择 {len(symbols)} 个标的"

    @app.callback(
        Output("factor-compute-factor-count", "children"),
        Input("factor-compute-factors", "value"),
    )
    def update_factor_count(factors):
        if not factors:
            return "未选择因子"
        return f"已选择 {len(factors)} 个因子"

    @app.callback(
        Output("factor-compute-progress", "value"),
        Output("factor-compute-progress", "label"),
        Output("factor-compute-status", "children"),
        Input("factor-compute-btn", "n_clicks"),
        State("factor-compute-symbols", "value"),
        State("factor-compute-factors", "value"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("factor-compute-btn", "disabled"), True, False),
            (Output("factor-compute-btn", "children"), "计算中...", "开始计算"),
        ],
    )
    def compute_factors(n_clicks, symbols, factors):
        if not symbols:
            return 0, "0%", html.Div("请先选择标的", className="text-warning")
        if not factors:
            return 0, "0%", html.Div("请先选择因子", className="text-warning")

        db = _get_db()
        total = len(symbols) * len(factors)
        completed = 0
        results = []
        errors = []

        for symbol in symbols:
            try:
                ohlcv_df = db.query_df(
                    "SELECT trade_date, open, high, low, close, volume FROM bars_daily WHERE ticker=? ORDER BY trade_date",
                    [symbol],
                )
                if ohlcv_df.is_empty():
                    errors.append(f"✗ {symbol}: 无数据")
                    continue
            except Exception as e:
                errors.append(f"✗ {symbol}: {str(e)[:60]}")
                continue

            for fname in factors:
                try:
                    factor_instance = FactorRegistry.get(fname)
                    computed = factor_instance.compute(ohlcv_df.clone())
                    new_cols = [c for c in computed.columns if c not in ohlcv_df.columns]
                    factor_df = computed.select(["trade_date"] + new_cols)
                    FactorStorage.save(symbol, factor_df)
                    results.append(f"✓ {symbol}/{fname}: {len(new_cols)} 列")
                except Exception as e:
                    errors.append(f"✗ {symbol}/{fname}: {str(e)[:60]}")
                completed += 1

        progress = int((completed / max(total, 1)) * 100)
        status_lines = results + errors
        status_el = html.Div([html.P(line) for line in status_lines[:30]])
        if len(status_lines) > 30:
            status_el.children = list(status_el.children) + [
                html.Small(f"...及其他 {len(status_lines)-30} 条结果")
            ]
        return progress, f"{progress}%", status_el

    @app.callback(
        Output("factor-preview-table-container", "children"),
        Output("factor-preview-stats", "children"),
        Input("factor-preview-symbol", "value"),
        prevent_initial_call=True,
    )
    def preview_factor_data(symbol):
        if not symbol:
            return html.P("请选择标的", className="text-muted"), "请选择标的"

        db = _get_db()
        try:
            ohlcv_df = db.query_df(
                "SELECT trade_date, open, high, low, close, volume FROM bars_daily WHERE ticker=? ORDER BY trade_date",
                [symbol],
            )
        except Exception:
            return html.P("数据查询失败", className="text-danger"), "数据加载失败"

        if ohlcv_df.is_empty():
            return html.P(f"未找到 {symbol} 的数据", className="text-warning"), "无数据"

        try:
            combined = FactorStorage.load_with_factors(symbol, ohlcv_df)
        except Exception:
            combined = ohlcv_df

        columns = [{"name": c, "id": c} for c in combined.columns]
        data = combined.tail(100).to_dicts()

        factor_cols = [c for c in combined.columns if c not in ("trade_date", "open", "high", "low", "close", "volume")]
        stats_lines = []
        if factor_cols:
            stats_lines.append(html.Strong(f"因子列 ({len(factor_cols)}个):"))
            stats_lines.append(html.Ul([html.Li(c) for c in factor_cols]))
        else:
            stats_lines.append(html.P("暂无因子数据，请先在'因子计算'标签页计算", className="text-muted"))

        if "close" in combined.columns:
            close_vals = combined["close"].drop_nulls()
            if len(close_vals) > 0:
                stats_lines.append(html.P(f"收盘价范围: {close_vals.min():.2f} - {close_vals.max():.2f}"))
                stats_lines.append(html.P(f"数据条数: {len(combined)}"))

        table = dash_table.DataTable(
            columns=columns,
            data=data,
            page_size=15,
            style_table={"overflowX": "auto"},
            style_cell={"padding": "4px", "fontSize": "12px"},
            style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
            style_data_conditional=[
                {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
            ],
        )
        return table, html.Div(stats_lines)


def _get_db():
    db_path = "./data/fisherquant.db"
    db = DuckDBManager()
    try:
        db.connect(db_path, read_pool_size=4)
    except Exception:
        pass
    return db
