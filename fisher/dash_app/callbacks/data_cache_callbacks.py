from dash import Input, Output, State, callback, no_update, html, dash_table
import dash_bootstrap_components as dbc

from fisher.dash_app.services import get_data_service


def register_data_cache_callbacks(app):
    @app.callback(
        Output("cached-table-container", "children", allow_duplicate=True),
        Input("cache-refresh-btn", "n_clicks"),
        State("data-center-tabs", "active_tab"),
        prevent_initial_call=True,
    )
    def force_refresh_cached(n, active_tab):
        if active_tab != "tab-cached":
            return no_update
        return _build_cached_table()

    @app.callback(
        Output("cached-table-container", "children"),
        Input("data-center-tabs", "active_tab"),
        Input("cache-market-filter", "value"),
        Input("cache-filter-input", "value"),
        Input("cache-refresh-btn", "n_clicks"),
        Input("cache-delete-btn", "n_clicks"),
        Input("auto-load-progress-poll", "n_intervals"),
    )
    def render_cached_table(active_tab, market_filter, filter_text, refresh_clicks, delete_clicks, load_poll):
        if active_tab != "tab-cached":
            return no_update

        svc = get_data_service()
        rows = svc.get_cached_table(
            market_filter=market_filter or "all",
            text_filter=filter_text or "",
        )
        if not rows:
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
            data=rows,
            row_selectable="multi",
            page_size=10,
            style_table={"overflowX": "auto"},
            style_cell={"padding": "8px", "fontSize": "13px"},
            style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
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

        tickers = [table_data[idx]["ticker"] for idx in selected_rows]
        svc = get_data_service()
        svc.delete_symbols(tickers)
        return _build_cached_table()


def _build_cached_table():
    svc = get_data_service()
    rows = svc.get_cached_table()
    if not rows:
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
        data=rows,
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
