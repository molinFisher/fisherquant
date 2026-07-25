import dash_bootstrap_components as dbc
from dash import html, dcc


def create_settings_layout():
    return dbc.Container(
        [
            html.H3("系统设置", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="回测参数", tab_id="tab-params", children=_create_params_tab()),
                    dbc.Tab(label="基准配置", tab_id="tab-benchmark", children=_create_benchmark_tab()),
                    dbc.Tab(label="数据刷新", tab_id="tab-refresh", children=_create_refresh_tab()),
                    dbc.Tab(label="数据源", tab_id="tab-source", children=_create_source_tab()),
                    dbc.Tab(label="系统日志", tab_id="tab-log", children=_create_log_tab()),
                ],
                id="settings-tabs",
                active_tab="tab-params",
                className="mb-3",
            ),
            html.Div(id="settings-save-status"),
        ]
    )


def _create_params_tab():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H5("全局回测参数", className="mb-3"),
                dbc.Row(
                    [
                        dbc.Col([dbc.Label("默认佣金率(%)"), dbc.Input(id="cfg-commission", type="number", value=0.025, min=0, max=1, step=0.001)], width=4),
                        dbc.Col([dbc.Label("最低佣金(元)"), dbc.Input(id="cfg-min-commission", type="number", value=5.0)], width=4),
                        dbc.Col([dbc.Label("默认滑点(%)"), dbc.Input(id="cfg-slippage", type="number", value=0.01, min=0, max=1, step=0.001)], width=4),
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col([dbc.Label("默认初始资金"), dbc.Input(id="cfg-capital", type="number", value=1000000, min=10000, step=10000)], width=4),
                        dbc.Col([dbc.Label("印花税(%)"), dbc.Input(id="cfg-stamp-duty", type="number", value=0.05, min=0, max=1, step=0.001)], width=4),
                        dbc.Col([dbc.Label("无风险利率(%)"), dbc.Input(id="cfg-risk-free", type="number", value=2.0, min=0, max=20, step=0.1)], width=4),
                    ],
                    className="mb-3",
                ),
                dbc.Button("保存", id="cfg-params-save-btn", color="primary"),
            ]
        ),
        className="mb-3",
    )


def _create_benchmark_tab():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H5("基准配置", className="mb-3"),
                dcc.RadioItems(
                    id="cfg-benchmark-radio",
                    options=[
                        {"label": "沪深300 (000300.SH)", "value": "000300.SH"},
                        {"label": "恒生指数 (HSI)", "value": "HSI"},
                        {"label": "混合基准", "value": "mixed"},
                    ],
                    value="000300.SH",
                    className="mb-3",
                ),
                html.Div(id="cfg-benchmark-mixed-config", style={"display": "none"}, children=[
                    dbc.Label("混合基准权重"),
                    dbc.Input(id="cfg-benchmark-weights", placeholder='[{"ticker": "000300.SH", "weight": 0.6}, ...]'),
                ]),
                dbc.Button("保存", id="cfg-benchmark-save-btn", color="primary", className="mt-2"),
            ]
        ),
        className="mb-3",
    )


def _create_refresh_tab():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H5("数据刷新策略", className="mb-3"),
                dbc.Label("日线更新时间"),
                dbc.Input(id="cfg-refresh-daily", placeholder="cron表达式, e.g., 0 16 * * 1-5", value="0 16 * * 1-5"),
                dbc.Label("分钟线更新间隔(分钟)", className="mt-2"),
                dbc.Input(id="cfg-refresh-minute", type="number", value=5, min=1),
                dbc.Label("行情刷新间隔(秒)", className="mt-2"),
                dbc.Input(id="cfg-refresh-quote", type="number", value=3, min=1),
                dbc.Button("保存", id="cfg-refresh-save-btn", color="primary", className="mt-3"),
            ]
        ),
        className="mb-3",
    )


def _create_source_tab():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H5("数据源管理", className="mb-3"),
                dbc.ListGroup(
                    [
                        dbc.ListGroupItem(
                            [
                                html.Div([html.Strong("AKShare (东方财富)"), dbc.Badge("启用", color="success", className="ms-2")]),
                                html.Small("A股数据源，当前唯一可用源", className="text-muted"),
                            ]
                        ),
                        dbc.ListGroupItem(
                            [
                                html.Div([html.Strong("Tushare"), dbc.Badge("不可用", color="secondary", className="ms-2")]),
                                html.Small("需要token，暂未支持", className="text-muted"),
                            ]
                        ),
                        dbc.ListGroupItem(
                            [
                                html.Div([html.Strong("Wind"), dbc.Badge("不可用", color="secondary", className="ms-2")]),
                                html.Small("商业数据终端，暂未支持", className="text-muted"),
                            ]
                        ),
                    ]
                ),
            ]
        ),
        className="mb-3",
    )


def _create_log_tab():
    return dbc.Card(
        dbc.CardBody(
            [
                html.H5("系统日志", className="mb-3"),
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Checklist(
                                id="cfg-log-filter",
                                options=[
                                    {"label": "DEBUG", "value": "DEBUG"},
                                    {"label": "INFO", "value": "INFO"},
                                    {"label": "WARNING", "value": "WARNING"},
                                    {"label": "ERROR", "value": "ERROR"},
                                ],
                                value=["INFO", "WARNING", "ERROR"],
                                inline=True,
                            ),
                            width=9,
                        ),
                        dbc.Col(
                            dbc.Button("刷新", id="cfg-log-refresh-btn", color="secondary", size="sm"),
                            width=3,
                            className="text-end",
                        ),
                    ],
                    className="mb-2 align-items-center",
                ),
                html.Pre(
                    id="cfg-log-content",
                    children="点击刷新加载日志...",
                    style={
                        "maxHeight": "400px", "overflow": "auto",
                        "backgroundColor": "#212529", "color": "#f8f9fa",
                        "padding": "12px", "borderRadius": "4px",
                        "fontSize": "12px", "fontFamily": "monospace",
                    },
                ),
            ]
        ),
        className="mb-3",
    )
