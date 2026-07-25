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
                        width=3,
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
                        width=3,
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
                        width=3,
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
                        width=3,
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
                        width=8,
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
                        width=4,
                    ),
                ]
            ),
        ]
    )
