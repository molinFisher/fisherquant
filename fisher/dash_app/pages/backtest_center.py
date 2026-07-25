import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table


STRATEGY_TYPE_OPTIONS = [
    {"label": "均线交叉 (SMA Cross)", "value": "sma_cross"},
    {"label": "MACD", "value": "macd"},
    {"label": "布林带 (Bollinger)", "value": "bollinger"},
    {"label": "RSI", "value": "rsi"},
    {"label": "买入持有 (Buy & Hold)", "value": "buy_and_hold"},
    {"label": "自定义 (DSL)", "value": "custom"},
]

BENCHMARK_OPTIONS = [
    {"label": "沪深300 (000300.SH)", "value": "000300.SH"},
    {"label": "恒生指数 (HSI)", "value": "HSI"},
    {"label": "无基准", "value": "none"},
]


def create_backtest_center_layout():
    return dbc.Container(
        [
            html.H3("回测中心", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="单策略回测", tab_id="tab-single", children=_create_single_tab()),
                    dbc.Tab(label="多策略对比", tab_id="tab-multi", children=_create_multi_tab()),
                    dbc.Tab(label="滚动优化", tab_id="tab-walkforward", children=_create_walkforward_tab()),
                    dbc.Tab(label="参数敏感性", tab_id="tab-sensitivity", children=_create_sensitivity_tab()),
                ],
                id="backtest-tabs",
                active_tab="tab-single",
                className="mb-3",
            ),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("回测详情")),
                    dbc.ModalBody(id="bt-modal-body"),
                    dbc.ModalFooter(
                        dbc.Button("关闭", id="bt-modal-close", className="ms-auto")
                    ),
                ],
                id="bt-detail-modal",
                size="xl",
            ),
            dcc.Store(id="bt-submitting", data=False),
            dcc.Store(id="bt-cancel-flag", data=False),
        ]
    )


def _create_single_tab():
    return dbc.Row(
        [
            dbc.Col(_create_config_panel(), width=4),
            dbc.Col(_create_results_panel(), width=8),
        ]
    )


def _create_multi_tab():
    return dbc.Card(
        dbc.CardBody([html.H5("多策略对比", className="text-muted"), html.P("选择最多5个策略同时回测，对比绩效表现")]),
    )


def _create_walkforward_tab():
    return dbc.Card(
        dbc.CardBody([html.H5("滚动优化", className="text-muted"), html.P("设置滚动窗口进行样本外测试")]),
    )


def _create_sensitivity_tab():
    return dbc.Card(
        dbc.CardBody([html.H5("参数敏感性分析", className="text-muted"), html.P("对策略参数进行网格搜索")]),
    )


def _create_config_panel():
    return dbc.Card(
        [
            dbc.CardHeader("回测配置"),
            dbc.CardBody(
                [
                    dbc.Label("策略选择"),
                    dcc.Dropdown(
                        id="bt-strategy-dropdown",
                        options=[],
                        placeholder="选择策略...",
                        clearable=False,
                    ),
                    dbc.Label("标的", className="mt-2"),
                    dcc.Dropdown(
                        id="bt-symbol-select",
                        options=[],
                        multi=True,
                        placeholder="选择标的（留空使用全部缓存）...",
                    ),
                    dbc.Label("日期范围", className="mt-2"),
                    dcc.DatePickerRange(
                        id="bt-date-range",
                        start_date="2024-01-01",
                        end_date="2025-06-30",
                        display_format="YYYY-MM-DD",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("初始资金"),
                                    dbc.Input(
                                        id="bt-capital",
                                        type="number",
                                        value=1000000,
                                        min=10000,
                                        step=10000,
                                    ),
                                ],
                                width=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("佣金率(%)"),
                                    dbc.Input(
                                        id="bt-commission",
                                        type="number",
                                        value=0.025,
                                        min=0,
                                        max=1,
                                        step=0.001,
                                    ),
                                ],
                                width=6,
                            ),
                        ],
                        className="mt-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("滑点(%)"),
                                    dbc.Input(
                                        id="bt-slippage",
                                        type="number",
                                        value=0.01,
                                        min=0,
                                        max=1,
                                        step=0.001,
                                    ),
                                ],
                                width=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("基准"),
                                    dcc.Dropdown(
                                        id="bt-benchmark",
                                        options=BENCHMARK_OPTIONS,
                                        value="000300.SH",
                                        clearable=False,
                                    ),
                                ],
                                width=6,
                            ),
                        ],
                        className="mt-2",
                    ),
                    dbc.Button(
                        "开始回测",
                        id="bt-run-btn",
                        color="primary",
                        className="mt-3 w-100",
                        disabled=False,
                    ),
                    dbc.Button(
                        "取消",
                        id="bt-cancel-btn",
                        color="danger",
                        outline=True,
                        className="mt-2 w-100",
                        style={"display": "none"},
                    ),
                    dbc.Progress(
                        id="bt-progress-bar",
                        value=0,
                        label="0%",
                        className="mt-2",
                        style={"height": "4px"},
                    ),
                    html.Div(id="bt-progress-text", className="text-muted small mt-1"),
                ]
            ),
        ]
    )


def _create_results_panel():
    return dbc.Card(
        [
            dbc.CardHeader("回测结果"),
            dbc.CardBody(
                [
                    html.Div(id="bt-summary-container", children="配置参数后点击"开始回测""),
                    html.Div(id="bt-equity-thumbnail", className="mt-3"),
                    html.Div(id="bt-results-link", className="mt-2"),
                ]
            ),
        ]
    )
