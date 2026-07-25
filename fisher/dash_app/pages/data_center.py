import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table


def create_data_center_layout():
    return dbc.Container(
        [
            html.H3("数据中心", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="数据查询", tab_id="tab-query", children=_create_query_tab()),
                    dbc.Tab(label="已缓存数据", tab_id="tab-cached", children=_create_cached_tab()),
                    dbc.Tab(label="高级功能", tab_id="tab-advanced", children=_create_advanced_tab()),
                ],
                id="data-center-tabs",
                active_tab="tab-query",
                className="mb-3",
            ),
            dcc.Store(id="search-results-store"),
            dcc.Store(id="fetch-progress-store"),
            dcc.Store(id="toast-trigger"),
            html.Div(id="data-center-content"),
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
                    )
                ],
                width=6,
            ),
        ]
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
