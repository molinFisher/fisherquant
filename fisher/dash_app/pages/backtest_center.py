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
    return dbc.Row(
        [
            dbc.Col(_create_multi_config_panel(), width=4),
            dbc.Col(_create_multi_results_panel(), width=8),
        ]
    )


def _create_multi_config_panel():
    return dbc.Card(
        [
            dbc.CardHeader("多策略配置"),
            dbc.CardBody(
                [
                    dbc.Label("选择策略 (最多5个)"),
                    dcc.Dropdown(
                        id="bt-multi-strategies",
                        options=[],
                        multi=True,
                        placeholder="选择多个策略进行对比...",
                    ),
                    dbc.Label("标的", className="mt-2"),
                    dcc.Dropdown(
                        id="bt-multi-symbols",
                        options=[],
                        multi=True,
                        placeholder="选择标的...",
                    ),
                    dbc.Label("日期范围", className="mt-2"),
                    dcc.DatePickerRange(
                        id="bt-multi-date-range",
                        start_date="2024-01-01",
                        end_date="2025-06-30",
                        display_format="YYYY-MM-DD",
                    ),
                    dbc.Row(
                        [
                            dbc.Col([dbc.Label("初始资金"), dbc.Input(id="bt-multi-capital", type="number", value=1000000)], width=6),
                            dbc.Col([dbc.Label("佣金率(%)"), dbc.Input(id="bt-multi-commission", type="number", value=0.025)], width=6),
                        ],
                        className="mt-2",
                    ),
                    dbc.Button("开始对比", id="bt-multi-run-btn", color="primary", className="mt-3 w-100"),
                    dbc.Progress(id="bt-multi-progress-bar", value=0, className="mt-2", style={"height": "4px"}),
                    html.Div(id="bt-multi-progress-text", className="text-muted small mt-1"),
                ]
            ),
        ]
    )


def _create_multi_results_panel():
    return dbc.Card(
        [
            dbc.CardHeader("对比结果"),
            dbc.CardBody([html.Div(id="bt-multi-results", children="选择策略后点击"开始对比"")]),
        ]
    )


def _create_walkforward_tab():
    return dbc.Row(
        [
            dbc.Col(_create_wf_config_panel(), width=4),
            dbc.Col(_create_wf_results_panel(), width=8),
        ]
    )


def _create_wf_config_panel():
    return dbc.Card(
        [
            dbc.CardHeader("滚动优化配置"),
            dbc.CardBody(
                [
                    dbc.Label("策略"),
                    dcc.Dropdown(id="bt-wf-strategy", options=[], placeholder="选择策略..."),
                    dbc.Label("窗口数量", className="mt-2"),
                    dbc.Input(id="bt-wf-windows", type="number", value=8, min=4, max=24),
                    dbc.Label("日期范围", className="mt-2"),
                    dcc.DatePickerRange(id="bt-wf-date-range", start_date="2020-01-01", end_date="2025-06-30", display_format="YYYY-MM-DD"),
                    dbc.Button("开始分析", id="bt-wf-run-btn", color="primary", className="mt-3 w-100"),
                    dbc.Progress(id="bt-wf-progress-bar", value=0, className="mt-2", style={"height": "4px"}),
                    html.Div(id="bt-wf-progress-text", className="text-muted small mt-1"),
                ]
            ),
        ]
    )


def _create_wf_results_panel():
    return dbc.Card(
        [
            dbc.CardHeader("滚动优化结果"),
            dbc.CardBody([html.Div(id="bt-wf-results", children="配置参数后点击"开始分析"")]),
        ]
    )


def _create_sensitivity_tab():
    return dbc.Row(
        [
            dbc.Col(_create_sens_config_panel(), width=4),
            dbc.Col(_create_sens_results_panel(), width=8),
        ]
    )


def _create_sens_config_panel():
    return dbc.Card(
        [
            dbc.CardHeader("敏感性分析配置"),
            dbc.CardBody(
                [
                    dbc.Label("策略"),
                    dcc.Dropdown(id="bt-sens-strategy", options=[], placeholder="选择策略..."),
                    dbc.Label("参数1", className="mt-2"),
                    dbc.Row(
                        [
                            dbc.Col(dcc.Dropdown(id="bt-sens-param1", placeholder="选择参数..."), width=4),
                            dbc.Col(dbc.Input(id="bt-sens-min1", type="number", placeholder="最小值"), width=3),
                            dbc.Col(dbc.Input(id="bt-sens-max1", type="number", placeholder="最大值"), width=3),
                            dbc.Col(dbc.Input(id="bt-sens-step1", type="number", placeholder="步长", value=5), width=2),
                        ]
                    ),
                    dbc.Label("参数2 (可选)", className="mt-2"),
                    dbc.Row(
                        [
                            dbc.Col(dcc.Dropdown(id="bt-sens-param2", placeholder="可选"), width=4),
                            dbc.Col(dbc.Input(id="bt-sens-min2", type="number", placeholder="最小值"), width=3),
                            dbc.Col(dbc.Input(id="bt-sens-max2", type="number", placeholder="最大值"), width=3),
                            dbc.Col(dbc.Input(id="bt-sens-step2", type="number", placeholder="步长", value=5), width=2),
                        ]
                    ),
                    dbc.Label("日期范围", className="mt-2"),
                    dcc.DatePickerRange(id="bt-sens-date-range", start_date="2024-01-01", end_date="2025-06-30", display_format="YYYY-MM-DD"),
                    dbc.Button("开始分析", id="bt-sens-run-btn", color="primary", className="mt-3 w-100"),
                    dbc.Progress(id="bt-sens-progress-bar", value=0, className="mt-2", style={"height": "4px"}),
                    html.Div(id="bt-sens-progress-text", className="text-muted small mt-1"),
                ]
            ),
        ]
    )


def _create_sens_results_panel():
    return dbc.Card(
        [
            dbc.CardHeader("敏感性分析结果"),
            dbc.CardBody([html.Div(id="bt-sens-results", children="配置参数后点击"开始分析"")]),
        ]
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
