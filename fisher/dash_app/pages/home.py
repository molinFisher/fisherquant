import dash_bootstrap_components as dbc
from dash import html


def create_home_layout():
    return dbc.Container(
        [
            html.H3("首页仪表盘", className="mb-4"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.H6("缓存标的", className="text-muted"),
                                html.H3("0", id="stat-tickers-count", className="text-primary"),
                                html.Small("全部标的", className="text-muted"),
                            ]),
                            className="stat-card",
                        ),
                        xs=6, sm=6, md=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.H6("A股", className="text-muted"),
                                html.H3("0", id="stat-ashare-count", className="text-success"),
                                html.Small("沪深股票", className="text-muted"),
                            ]),
                            className="stat-card",
                        ),
                        xs=6, sm=6, md=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.H6("港股", className="text-muted"),
                                html.H3("0", id="stat-hk-count", className="text-info"),
                                html.Small("港股通", className="text-muted"),
                            ]),
                            className="stat-card",
                        ),
                        xs=6, sm=6, md=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.H6("数据条数", className="text-muted"),
                                html.H3("0", id="stat-records-count", className="text-warning"),
                                html.Small("最近更新: -", id="stat-last-update", className="text-muted"),
                            ]),
                            className="stat-card",
                        ),
                        xs=6, sm=6, md=3,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("最近回测"),
                                dbc.CardBody(id="recent-backtests", children="暂无回测记录"),
                            ]
                        ),
                        xs=12, lg=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("快捷操作"),
                                dbc.CardBody(
                                    [
                                        dbc.Button("拉取数据", id="quick-fetch", color="primary", className="mb-2 w-100"),
                                        dbc.Button("创建策略", id="quick-strategy", color="success", className="mb-2 w-100"),
                                        dbc.Button("运行回测", id="quick-backtest", color="warning", className="w-100"),
                                    ]
                                ),
                            ]
                        ),
                        xs=12, lg=4,
                    ),
                ],
                className="mb-4",
            ),
            html.Div(id="first-use-guide", children=_build_first_use_guide()),
        ]
    )


def _build_first_use_guide():
    return dbc.Card(
        [
            dbc.CardHeader([html.H5("新手引导"), html.Small("3步开始量化交易", className="text-muted")]),
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            html.Div(
                                [
                                    html.Div("1", className="step-number"),
                                    html.H6("获取数据", className="mt-2"),
                                    html.P("在数据中心搜索并下载A股标的的历史行情数据", className="text-muted small"),
                                    dbc.Button("前往数据中心", href="/data-center", color="outline-primary", size="sm"),
                                ],
                                className="text-center p-3",
                            ),
                            xs=12, md=4,
                        ),
                        dbc.Col(
                            html.Div(
                                [
                                    html.Div("2", className="step-number"),
                                    html.H6("创建策略", className="mt-2"),
                                    html.P("使用内置模板或自定义DSL创建交易策略", className="text-muted small"),
                                    dbc.Button("前往策略中心", href="/strategy-center", color="outline-primary", size="sm"),
                                ],
                                className="text-center p-3",
                            ),
                            xs=12, md=4,
                        ),
                        dbc.Col(
                            html.Div(
                                [
                                    html.Div("3", className="step-number"),
                                    html.H6("运行回测", className="mt-2"),
                                    html.P("在回测中心配置参数,运行回测并查看可视化报告", className="text-muted small"),
                                    dbc.Button("前往回测中心", href="/backtest-center", color="outline-primary", size="sm"),
                                ],
                                className="text-center p-3",
                            ),
                            xs=12, md=4,
                        ),
                    ],
                    className="mt-2",
                ),
            ),
        ],
        className="mt-3",
    )
