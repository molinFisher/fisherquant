"""已缓存数据目录页回调（PRD FR-8.1 / FR-8.2 / U-1 / U-3）。

V1.4 起目录页数据源由 bars_daily 聚合切换为 cache_catalog（v_cache_summary 视图）：
- 每行渲染紧凑覆盖度徽标（日/分/实/复，✓绿✗灰，hover 出类型名 + 边界）；
- 条数按类型分别统计（日线条数 / 分钟条数）；
- 「数据类型」多选筛选为 AND 语义（勾选日线+分钟 = 两者兼备的标的）。

轮询（3s）只更新 DataTable.data，绝不重建容器（保留翻页位置，V1.3 回归修复）。

联动：
- 联动 B（IC-2 / U-2）：看板跳转过来时预置筛选 + 激活 tab-cached，消费后清空 ?focus=；
- 联动 A（IC-1 / FR-3.1 / FR-7.5）：行内「加入看板」/ 批量加入 → 写看板自选 +
  置 auto_load_enabled=TRUE + 跳转行情看板定位该标的。
"""

from dash import Input, Output, State, callback, no_update, html, dash_table

from fisher.dash_app.services import get_data_service, get_cache_catalog_service

# 覆盖度徽标：列名缩写 -> (has_* 字段, 类型全名)。U-1：日/分/实/复/财 五类（Task #24）。
_BADGES = [
    ("日", "has_daily", "日线"),
    ("分", "has_minute", "分钟线"),
    ("实", "has_realtime", "实时快照"),
    ("复", "has_adj", "复权因子"),
    ("财", "has_financials", "财务数据"),
]


def _coverage_markdown(row: dict) -> str:
    """单元格内紧凑 icon-only 徽标组（U-1）：✓绿 ✗灰，hover 显示类型名与边界。"""
    spans = []
    for label, flag_col, full_name in _BADGES:
        has = bool(row.get(flag_col))
        if flag_col == "has_daily" and has:
            tip = f"{full_name} {row.get('daily_start', '')} ~ {row.get('daily_end', '')}"
        elif flag_col == "has_minute" and has:
            periods = row.get("minute_periods")
            tip = f"{full_name}（近 60 天窗口）周期：{periods or '5'}"
        elif flag_col == "has_realtime" and has:
            tip = f"{full_name} 最新 {row.get('realtime_ts', '')}"
        elif flag_col == "has_financials" and has:
            tip = f"{full_name} 最新报告期 {row.get('fin_report_end', '')}"
        elif has:
            tip = f"已缓存{full_name}"
        else:
            tip = f"未缓存{full_name}"
        color = "#28a745" if has else "#c8ccd0"
        spans.append(
            f'<span title="{tip}" style="color:{color};font-weight:600;'
            f'margin-right:4px">{label}{"✓" if has else "✗"}</span>'
        )
    return "".join(spans)


def _catalog_rows(market_filter="all", type_filter=None, text_filter="") -> list[dict]:
    """从 cache_catalog（v_cache_summary）构建目录页行数据。"""
    catalog = get_cache_catalog_service()
    rows = catalog.get_cache_summary(
        market=market_filter or "all",
        data_types=list(type_filter or []),
        text=text_filter or "",
    )
    out = []
    for r in rows:
        out.append(
            {
                "ticker": r.get("ticker", ""),
                "name": r.get("name", "") or "—",
                "market": r.get("market", ""),
                "coverage": _coverage_markdown(r),
                "daily_rows": r.get("daily_rows", 0),
                "minute_rows": r.get("minute_rows", 0),
                "start_date": str(r.get("daily_start") or "—"),
                "end_date": str(r.get("daily_end") or "—"),
                # 联动 A（IC-1 / FR-3.1）：去行情看板并定位该标的
                "add_board": f"[加入看板](/quote-board?focus={r.get('ticker', '')})",
            }
        )
    return out


_COLUMNS = [
    {"name": "代码", "id": "ticker"},
    {"name": "名称", "id": "name"},
    {"name": "市场", "id": "market"},
    {"name": "覆盖度", "id": "coverage", "presentation": "markdown"},
    {"name": "日线条数", "id": "daily_rows"},
    {"name": "分钟条数", "id": "minute_rows"},
    {"name": "起始日期", "id": "start_date"},
    {"name": "最新日期", "id": "end_date"},
    {"name": "加入看板", "id": "add_board", "presentation": "markdown"},
]


def _make_table(rows: list[dict]) -> dash_table.DataTable:
    return dash_table.DataTable(
        id="cached-data-table",
        columns=_COLUMNS,
        data=rows,
        row_selectable="multi",
        page_size=10,
        markdown_options={"html": True},
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontSize": "13px"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
        ],
    )


def register_data_cache_callbacks(app):
    @app.callback(
        Output("cached-table-container", "children", allow_duplicate=True),
        Input("cache-refresh-btn", "n_clicks"),
        State("data-center-tabs", "active_tab"),
        State("cache-market-filter", "value"),
        State("cache-type-filter", "value"),
        State("cache-filter-input", "value"),
        prevent_initial_call=True,
    )
    def force_refresh_cached(n, active_tab, market_filter=None, type_filter=None,
                             filter_text=None):
        if active_tab != "tab-cached":
            return no_update
        return _build_cached_table(market_filter, type_filter, filter_text)

    @app.callback(
        Output("cached-table-container", "children"),
        Input("data-center-tabs", "active_tab"),
        Input("cache-market-filter", "value"),
        Input("cache-type-filter", "value"),
        Input("cache-filter-input", "value"),
        Input("cache-refresh-btn", "n_clicks"),
        Input("cache-delete-confirm-btn", "n_clicks"),
    )
    def render_cached_table(
        active_tab, market_filter, type_filter, filter_text,
        refresh_clicks, confirm_clicks
    ):
        if active_tab != "tab-cached":
            return no_update

        rows = _catalog_rows(market_filter, type_filter, filter_text)
        if not rows:
            return _empty_cached_table()
        return _make_table(rows)

    @app.callback(
        Output("cached-table-container", "children", allow_duplicate=True),
        Output("cache-delete-modal", "is_open", allow_duplicate=True),
        Input("cache-delete-confirm-btn", "n_clicks"),
        State("cached-data-table", "selected_rows"),
        State("cached-data-table", "data"),
        State("cache-delete-type", "value"),
        State("cache-market-filter", "value"),
        State("cache-type-filter", "value"),
        State("cache-filter-input", "value"),
        prevent_initial_call=True,
    )
    def confirm_delete_selected(n_clicks, selected_rows, table_data,
                                delete_type="all", market_filter="all",
                                type_filter=None, filter_text=""):
        """二次确认后的真正删除（FR-8.3 / 验收 11）。

        整行删除：5 类物理数据 + 目录行全清；
        按类型删除：仅删该类数据，同事务 has_<type>=FALSE、边界置 NULL，
        其余类型不受影响（FR-1.5，由服务层保证）。
        """
        if not selected_rows or not table_data:
            return no_update, False

        tickers = [table_data[idx]["ticker"] for idx in selected_rows]
        svc = get_data_service()
        if (delete_type or "all") == "all":
            svc.delete_symbols(tickers)
        else:
            svc.delete_symbols_by_type(tickers, delete_type)
        return _build_cached_table(market_filter, type_filter, filter_text), False

    @app.callback(
        Output("cached-data-table", "data"),
        Input("auto-load-progress-poll", "n_intervals"),
        State("data-center-tabs", "active_tab"),
        State("cache-market-filter", "value"),
        State("cache-type-filter", "value"),
        State("cache-filter-input", "value"),
    )
    def poll_update_cached_data(load_poll, active_tab, market_filter,
                                type_filter, filter_text):
        """每 3 秒的自动加载轮询只更新 DataTable 的 data 属性，不重建组件。

        这样 Dash 会保留 cached-data-table 的 page_current（翻页位置）与 selected_rows，
        修复「用户翻到后续页后，轮询一触发就跳回第 1 页」的缺陷。结构重建（会重置翻页）
        只发生在用户真正操作（切 tab / 改筛选 / 刷新 / 删除）时，由 render_cached_table 负责。
        """
        if active_tab != "tab-cached":
            return no_update
        return _catalog_rows(market_filter, type_filter, filter_text) or []

    @app.callback(
        Output("cache-delete-modal", "is_open"),
        Output("cache-delete-modal-body", "children"),
        Input("cache-delete-btn", "n_clicks"),
        Input("cache-delete-cancel-btn", "n_clicks"),
        State("cached-data-table", "selected_rows"),
        State("cached-data-table", "data"),
        State("cache-delete-type", "value"),
        prevent_initial_call=True,
    )
    def toggle_delete_modal(open_clicks, cancel_clicks, selected_rows,
                            table_data, delete_type="all"):
        """「删除选中」→ 弹二次确认；「取消」→ 关闭（FR-8.3 / U-4）。"""
        from dash import ctx
        trigger = getattr(ctx, "triggered_id", None)
        if trigger == "cache-delete-cancel-btn":
            return False, no_update
        if not selected_rows or not table_data:
            return False, no_update
        tickers = [table_data[idx]["ticker"] for idx in selected_rows]
        return True, _delete_confirm_text(tickers, delete_type or "all")

    @app.callback(
        # 联动 B（IC-2 / U-2）：看板跳转过来时预置筛选并激活「已缓存」tab，消费后清空 ?focus=
        Output("cache-filter-input", "value"),
        Output("data-center-tabs", "active_tab"),
        Output("url", "search"),
        Input("url", "search"),
        State("url", "pathname"),
        prevent_initial_call=True,
    )
    def consume_focus(search, pathname):
        from urllib.parse import parse_qs
        if not search or pathname != "/data-center":
            return no_update, no_update, no_update
        q = parse_qs(search.lstrip("?"))
        focus = (q.get("focus") or [None])[0]
        tab = (q.get("tab") or [None])[0]
        if not focus or tab != "tab-cached":
            return no_update, no_update, no_update
        # 预置筛选 + 激活 tab；清空 focus 避免手动刷新反复置顶（U-2）
        return focus, "tab-cached", "?tab=tab-cached"

    @app.callback(
        # 联动 A（IC-1 / FR-3.1）：批量把当前筛选结果加入行情看板自选 +
        # 置 auto_load_enabled=TRUE（FR-7.5）+ 跳转看板
        Output("url", "pathname", allow_duplicate=True),
        Output("url", "search", allow_duplicate=True),
        Input("cache-add-all-board-btn", "n_clicks"),
        State("cache-market-filter", "value"),
        State("cache-type-filter", "value"),
        State("cache-filter-input", "value"),
        prevent_initial_call=True,
    )
    def batch_add_to_board(n_clicks, market_filter, type_filter, filter_text):
        if not n_clicks:
            return no_update, no_update
        catalog = get_cache_catalog_service()
        rows = catalog.get_cache_summary(
            market=market_filter or "all",
            data_types=list(type_filter or []),
            text=filter_text or "",
        )
        tickers = [r["ticker"] for r in rows]
        if not tickers:
            return no_update, no_update
        # 统一收敛到看板自选（去重）
        from ..callbacks.quote_callbacks import _load_watchlist, _save_watchlist
        watchlist = _load_watchlist() or []
        for t in tickers:
            if t not in watchlist:
                watchlist.append(t)
            try:
                catalog.set_auto_load_enabled(t, True)
            except Exception:
                pass
        _save_watchlist(watchlist)
        return "/quote-board", "?focus=" + tickers[0]


_TYPE_NAMES = {
    "daily": "日线", "minute": "分钟线", "realtime": "实时快照",
    "adj": "复权因子", "financials": "财务数据",
}


def _delete_confirm_text(tickers: list[str], delete_type: str):
    """确认文案明示删除的数据类型与影响范围（FR-8.3）。"""
    shown = "、".join(tickers[:5]) + ("等" if len(tickers) > 5 else "")
    if delete_type == "all":
        scope = html.P([
            "将删除以上标的的",
            html.Strong("全部缓存数据（日线/分钟/实时/复权/财务）"),
            "并移出缓存目录，操作不可恢复。",
        ])
    else:
        tname = _TYPE_NAMES.get(delete_type, delete_type)
        scope = html.P([
            "将仅删除以上标的的",
            html.Strong(f"【{tname}】"),
            f"数据；其他类型（如{'日线' if delete_type != 'daily' else '分钟线'}等）不受影响。",
        ])
    return html.Div([
        html.P(f"已选中 {len(tickers)} 个标的：{shown}"),
        scope,
    ])


def _build_cached_table(market_filter="all", type_filter=None, filter_text=""):
    rows = _catalog_rows(market_filter, type_filter, filter_text)
    if not rows:
        return _empty_cached_table()
    return _make_table(rows)


def _empty_cached_table():
    return html.Div(
        [
            html.H5("暂无缓存数据", className="text-muted text-center mt-4"),
            html.P('请先在"数据查询"标签页中搜索并获取数据', className="text-muted text-center"),
        ]
    )
