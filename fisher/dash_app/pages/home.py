import dash_bootstrap_components as dbc
from dash import html


def create_home_layout():
    return dbc.Container(
        [
            html.H3("首页仪表盘", className="mb-4"),
            dbc.Row(
                [
                    dbc.Col(create_stat_card("缓存标的", "0", "全部标的", "primary"), width=3),
                    dbc.Col(create_stat_card("A股", "0", "沪深股票", "success"), width=3),
                    dbc.Col(create_stat_card("港股", "0", "港股通", "info"), width=3),
                    dbc.Col(create_stat_card("数据条数", "0", "最近更新: -", "warning"), width=3),
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


def create_stat_card(title, value, subtitle, color):
    return dbc.Card(
        [
            dbc.CardBody(
                [
                    html.H6(title, className="text-muted"),
                    html.H3(value, className=f"text-{color}"),
                    html.Small(subtitle, className="text-muted"),
                ]
            )
        ]
    )
