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
    )
    def render_cached_table(
        active_tab, market_filter, filter_text, refresh_clicks, delete_clicks
    ):
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
            {"name": "名称", "id": "name"},
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


    @app.callback(
        Output("cached-data-table", "data"),
        Input("auto-load-progress-poll", "n_intervals"),
        State("data-center-tabs", "active_tab"),
        State("cache-market-filter", "value"),
        State("cache-filter-input", "value"),
    )
    def poll_update_cached_data(load_poll, active_tab, market_filter, filter_text):
        """每 3 秒的自动加载轮询只更新 DataTable 的 data 属性，不重建组件。

        这样 Dash 会保留 cached-data-table 的 page_current（翻页位置）与 selected_rows，
        修复「用户翻到后续页后，轮询一触发就跳回第 1 页」的缺陷。结构重建（会重置翻页）
        只发生在用户真正操作（切 tab / 改筛选 / 刷新 / 删除）时，由 render_cached_table 负责。
        """
        if active_tab != "tab-cached":
            return no_update
        svc = get_data_service()
        rows = svc.get_cached_table(
            market_filter=market_filter or "all",
            text_filter=filter_text or "",
        )
        return rows or []


def _build_cached_table():
    svc = get_data_service()
    rows = svc.get_cached_table()
    if not rows:
        return _empty_cached_table()

    columns = [
        {"name": "代码", "id": "ticker"},
        {"name": "名称", "id": "name"},
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
