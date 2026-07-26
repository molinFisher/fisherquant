import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update, ctx
import logging

logger = logging.getLogger(__name__)


def create_data_center_layout():
    return dbc.Container(
        [
            html.H3("数据中心", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="数据查询", tab_id="tab-query", children=_create_query_tab()),
                    dbc.Tab(label="已缓存数据", tab_id="tab-cached", children=_create_cached_tab()),
                    dbc.Tab(label="高级功能", tab_id="tab-advanced", children=_create_advanced_tab()),
                    dbc.Tab(label="自动加载", tab_id="tab-auto-load", children=_create_auto_load_tab()),
                ],
                id="data-center-tabs",
                active_tab="tab-query",
                className="mb-3",
            ),
            dcc.Store(id="search-results-store"),
            dcc.Store(id="fetch-progress-status"),
            dcc.Store(id="fetch-progress-store"),
            dcc.Store(id="toast-trigger"),
            dcc.Interval(id="fetch-progress-poll", interval=1000),
            dcc.Interval(id="auto-load-progress-poll", interval=3000),
            html.Div(id="data-center-content"),
            _create_financials_modal(),
        ]
    )


def _create_query_tab():
    return dbc.Row(
        [
            dbc.Col(
                [
                    dbc.Card(
                        [
                            dbc.CardHeader("标的搜索"),
                            dbc.CardBody(
                                [
                                    dbc.Input(
                                        id="symbol-search-input",
                                        type="text",
                                        placeholder="输入股票代码或名称（至少2个字符）...",
                                        debounce=True,
                                    ),
                                    dcc.Dropdown(id="symbol-search-results", placeholder="搜索结果将显示在这里..."),
                                    html.Div(id="search-status", className="text-muted small mt-1"),
                                ]
                            ),
                        ],
                        className="mb-3",
                    ),
                    dbc.Card(
                        [
                            dbc.CardHeader("获取数据"),
                            dbc.CardBody(
                                [
                                    dbc.Label("时间范围"),
                                    dcc.DatePickerRange(
                                        id="date-range-picker",
                                        start_date="2024-01-01",
                                        end_date="2024-12-31",
                                        display_format="YYYY-MM-DD",
                                    ),
                                    dbc.Label("数据类型", className="mt-2"),
                                    dcc.RadioItems(
                                        id="data-type-radio",
                                        options=[
                                            {"label": "日线", "value": "daily"},
                                            {"label": "分钟线", "value": "minute"},
                                            {"label": "财务数据", "value": "financials"},
                                        ],
                                        value="daily",
                                    ),
                                    html.Div(
                                        id="minute-period-container",
                                        children=[
                                            dbc.Label("分钟周期", className="mt-2"),
                                            dcc.Dropdown(
                                                id="minute-period-selector",
                                                options=[
                                                    {"label": "1分钟", "value": "1min"},
                                                    {"label": "5分钟", "value": "5min"},
                                                    {"label": "15分钟", "value": "15min"},
                                                    {"label": "30分钟", "value": "30min"},
                                                    {"label": "60分钟", "value": "60min"},
                                                ],
                                                value="5min",
                                            ),
                                        ],
                                        style={"display": "none"},
                                    ),
                                    dbc.Label("批量输入", className="mt-2"),
                                    dcc.Textarea(
                                        id="batch-symbols-input",
                                        placeholder="输入多个标的，逗号或换行分隔...",
                                        rows=3,
                                    ),
                                    dbc.Button(
                                        "开始获取数据",
                                        id="fetch-data-button",
                                        color="primary",
                                        className="mt-2 w-100",
                                    ),
                                    dbc.Progress(
                                        id="fetch-progress-bar",
                                        value=0,
                                        label="0%",
                                        className="mt-2",
                                        style={"height": "4px"},
                                    ),
                                    html.Div(id="fetch-status", className="mt-2"),
                                ]
                            ),
                        ]
                    ),
                ],
                width=6,
            ),
            dbc.Col(
                [
                    dbc.Card(
                        [
                            dbc.CardHeader("获取列表"),
                            dbc.CardBody(id="fetch-list", children="请先搜索并选择标的"),
                        ]
                    ),
                    html.Br(),
                    dbc.Card(
                        [
                            dbc.CardHeader("财务数据查询"),
                            dbc.CardBody(
                                [
                                    dbc.Input(
                                        id="financials-symbol-input",
                                        placeholder="输入标的代码...",
                                        className="mb-2",
                                    ),
                                    dbc.Button(
                                        "查询财务数据",
                                        id="query-financials-btn",
                                        color="info",
                                        className="w-100",
                                    ),
                                ]
                            ),
                        ]
                    ),
                ],
                width=6,
            ),
        ],
    )


def _create_auto_load_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("自动加载进度"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="auto-load-progress-status", className="mb-2"),
                                        dbc.Progress(id="auto-load-progress-bar", value=0, label="0%",
                                                     className="mb-2", style={"height": "24px"}),
                                        html.Div(id="auto-load-progress-detail", className="text-muted small"),
                                    ]
                                ),
                            ],
                            className="mb-3",
                        ),
                        width=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("控制"),
                                dbc.CardBody(
                                    [
                                        dbc.Button("开始自动加载", id="auto-load-start-btn",
                                                   color="primary", className="w-100 mb-2"),
                                        dbc.Button("暂停", id="auto-load-pause-btn",
                                                   color="warning", className="w-100 mb-2"),
                                        html.Div(id="auto-load-action-feedback", className="text-muted small mt-1"),
                                    ]
                                ),
                            ]
                        ),
                        width=4,
                    ),
                ]
            ),
        ]
    )


def _create_financials_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("财务数据")),
            dbc.ModalBody(id="financials-modal-body", children="加载中..."),
            dbc.ModalFooter(
                dbc.Button("关闭", id="close-financials-modal", className="ms-auto")
            ),
        ],
        id="financials-modal",
        size="lg",
    )


def _create_cached_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.InputGroup(
                                [
                                    dbc.Input(placeholder="筛选标的...", id="cache-filter-input"),
                                    dbc.Button("刷新", id="cache-refresh-btn", color="secondary"),
                                    dbc.Button("删除选中", id="cache-delete-btn", color="danger"),
                                ],
                                className="mb-2",
                            )
                        ],
                        width=12,
                    ),
                ]
            ),
            dcc.RadioItems(
                id="cache-market-filter",
                options=[
                    {"label": "全部", "value": "all"},
                    {"label": "A股", "value": "a_share"},
                    {"label": "港股", "value": "hk_connect"},
                ],
                value="all",
                inline=True,
                className="mb-2",
            ),
            html.Div(id="cached-table-container"),
        ]
    )


def register_data_center_callbacks(app):
    from fisher.dash_app.services import get_auto_load_service

    @app.callback(
        Output("auto-load-progress-status", "children"),
        Output("auto-load-progress-bar", "value"),
        Output("auto-load-progress-bar", "label"),
        Output("auto-load-progress-detail", "children"),
        Output("auto-load-start-btn", "disabled"),
        Output("auto-load-pause-btn", "disabled"),
        Input("auto-load-progress-poll", "n_intervals"),
    )
    def update_auto_load_progress(n):
        try:
            svc = get_auto_load_service()
            progress = svc.get_progress()
        except Exception as e:
            logger.error("auto-load progress check failed: %s", e)
            return "状态检查失败", 0, "0%", "", True, True

        phase = progress.get("phase", "idle")
        current = int(progress.get("current", 0))
        total = int(progress.get("total", 0))
        skipped = int(progress.get("skipped", 0))
        loaded = current - skipped

        is_running = phase == "initial_load"
        start_disabled = is_running
        pause_disabled = not is_running

        if phase == "initial_load" and total > 0:
            pct = int(loaded * 100 / total) if total > 0 else 0
            detail_parts = []
            if loaded > 0:
                detail_parts.append(f"已加载 {loaded}/{total}")
            if skipped > 0:
                detail_parts.append(f"跳过 {skipped}")
            if loaded == 0 and skipped > 0:
                detail_parts = [f"全部失败（{skipped} 个跳过）"]
            elif loaded == 0 and skipped == 0:
                detail_parts = [f"等待中..."]
            detail = "，".join(detail_parts)
            return (
                dbc.Badge("加载中", color="info", className="me-2"),
                pct, f"{loaded}/{total} ({pct}%)",
                detail, start_disabled, pause_disabled,
            )
        if phase == "complete" and total > 0:
            return (
                dbc.Badge("已完成", color="success", className="me-2"),
                100, f"{total}/{total} (100%)",
                f"共加载 {total} 个标的，数据就绪",
                start_disabled, pause_disabled,
            )
        if phase == "error":
            return (
                dbc.Badge("出错", color="danger", className="me-2"),
                0, "错误",
                progress.get("message", "加载过程发生错误"),
                start_disabled, pause_disabled,
            )
        return (
            dbc.Badge("空闲", color="secondary", className="me-2"),
            0, "0%",
            "自动加载未运行，请点击「开始自动加载」",
            start_disabled, pause_disabled,
        )

    @app.callback(
        Output("fetch-progress-bar", "value"),
        Output("fetch-progress-bar", "label"),
        Input("fetch-progress-poll", "n_intervals"),
        State("fetch-progress-status", "data"),
    )
    def update_fetch_progress(n, data):
        if not data:
            return 0, "0%"
        current = data.get("current", 0)
        total = data.get("total", 1)
        pct = int(current * 100 / max(total, 1))
        return pct, f"{current}/{total} ({pct}%)"

    @app.callback(
        Output("auto-load-action-feedback", "children"),
        Output("auto-load-start-btn", "disabled", allow_duplicate=True),
        Output("auto-load-pause-btn", "disabled", allow_duplicate=True),
        Input("auto-load-start-btn", "n_clicks"),
        Input("auto-load-pause-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_auto_load_action(start_clicks, pause_clicks):
        if not ctx.triggered:
            return no_update
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            svc = get_auto_load_service()
            if trigger_id == "auto-load-start-btn":
                svc.reset_load()
                svc.start_background_load()
                return "自动加载已启动，请查看进度...", True, False
            else:
                svc.set_status("phase", "idle")
                return "自动加载已暂停", False, True
        except Exception as e:
            logger.error("auto-load action failed: %s", e)
            return f"操作失败: {e}", False, False


def _create_advanced_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("自动刷新设置"),
                                    dbc.CardBody(
                                        [
                                            dbc.Checkbox(
                                                id="auto-refresh-toggle",
                                                label="启用自动刷新",
                                                value=False,
                                            ),
                                            dbc.Input(
                                                id="auto-refresh-cron",
                                                placeholder="cron表达式，例如: 0 16 * * 1-5",
                                                className="mt-2",
                                            ),
                                            html.Div(id="next-refresh-time", className="text-muted small mt-1"),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("数据导出"),
                                    dbc.CardBody(
                                        [
                                            dcc.Dropdown(
                                                id="export-format-dropdown",
                                                options=[
                                                    {"label": "CSV", "value": "csv"},
                                                    {"label": "Excel", "value": "xlsx"},
                                                    {"label": "Parquet", "value": "parquet"},
                                                ],
                                                value="csv",
                                                placeholder="选择导出格式",
                                            ),
                                            dbc.Label("筛选标的（可选，逗号分隔）", className="mt-2"),
                                            dbc.Input(
                                                id="export-symbol-input",
                                                placeholder="如: 600519.SH, 000001.SZ",
                                                className="mb-1",
                                            ),
                                            dbc.Row([
                                                dbc.Col([
                                                    dbc.Label("起始日期"),
                                                    dcc.DatePickerSingle(id="export-start-date", date=""),
                                                ]),
                                                dbc.Col([
                                                    dbc.Label("截止日期"),
                                                    dcc.DatePickerSingle(id="export-end-date", date=""),
                                                ]),
                                            ], className="mb-1"),
                                            dbc.Button(
                                                "导出数据",
                                                id="export-data-btn",
                                                color="primary",
                                                className="mt-2 w-100",
                                            ),
                                            dcc.Download(id="download-data"),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader("复权因子"),
                                    dbc.CardBody(
                                        [
                                            dbc.Input(
                                                id="adj-factor-symbol",
                                                placeholder="输入标的代码",
                                                className="mb-2",
                                            ),
                                            dbc.Button(
                                                "查询复权因子",
                                                id="fetch-adj-factor-btn",
                                                color="info",
                                                className="w-100",
                                            ),
                                            html.Div(id="adj-factor-result", className="mt-2"),
                                        ]
                                    ),
                                ],
                            ),
                        ],
                        width=6,
                    ),
                ]
            ),
        ]
    )
