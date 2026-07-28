import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table


def create_quote_board_layout():
    return dbc.Container(
        [
            html.H3("行情看板", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.InputGroup(
                                [
                                    dcc.Dropdown(
                                        id="qb-add-symbol-dropdown",
                                        options=[],
                                        placeholder="搜索并添加标的...",
                                        style={"flex": "1"},
                                    ),
                                    dbc.Button("添加", id="qb-add-btn", color="primary"),
                                ],
                                className="mb-2",
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Button("手动刷新", id="qb-manual-refresh", color="secondary", className="me-2"),
                            dbc.Checkbox(id="qb-auto-refresh-toggle", label="自动刷新(60s)", value=True, className="d-inline-block me-3"),
                            dbc.Button("清空自选", id="qb-clear-all-btn", color="danger", outline=True, size="sm"),
                        ],
                        width=6,
                        className="text-end",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("复权口径", className="me-2 small mb-0"),
                            dcc.RadioItems(
                                id="qb-adj-mode",
                                options=[
                                    {"label": "不复权", "value": "none"},
                                    {"label": "前复权", "value": "qfq"},
                                    {"label": "后复权", "value": "hfq"},
                                ],
                                value="none",
                                inline=True,
                                className="small",
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("分钟周期", className="me-2 small mb-0"),
                            dcc.RadioItems(
                                id="qb-minute-period",
                                options=[
                                    {"label": "1m", "value": "1"},
                                    {"label": "5m", "value": "5"},
                                    {"label": "15m", "value": "15"},
                                    {"label": "30m", "value": "30"},
                                    {"label": "60m", "value": "60"},
                                ],
                                value="5",
                                inline=True,
                                className="small",
                            ),
                        ],
                        width=6,
                    ),
                ],
                className="mb-2 align-items-center",
            ),
    html.Div(id="qb-health-div", className="mb-2"),
    html.Div(id="qb-delete-bar", className="mb-2"),  # FR-1.2：批量删除按钮容器
    html.Div(id="qb-table-container"),
    # FR-2.1：K 线 Tabs（分钟线 + 日线）
    dbc.Tabs(
        [
            dbc.Tab(dcc.Graph(id="qb-minute-chart", figure={"data": [], "layout": {}}),
                    label="分钟线", tab_id="tab-minute"),
            dbc.Tab(
                html.Div([
                    dcc.RadioItems(
                        id="qb-daily-range",
                        options=[
                            {"label": "1月", "value": 20},
                            {"label": "3月", "value": 60},
                            {"label": "6月", "value": 120},
                            {"label": "1年", "value": 250},
                        ],
                        value=120,
                        inline=True,
                        className="small mb-2",
                        inputClassName="me-1",
                        labelClassName="me-3",
                    ),
                    dcc.Graph(id="qb-daily-chart", figure={"data": [], "layout": {}}),
                ]),
                label="日线", tab_id="tab-daily",
            ),
        ],
        id="qb-chart-tabs",
        className="mt-2",
    ),
            dcc.Store(id="qb-watchlist-store", data=[]),
            dcc.Store(id="qb-chart-symbol", data=None),  # FR-2.3：当前 K 线标的
            dcc.Interval(id="qb-refresh-interval", interval=60000, disabled=False),
            dcc.Store(id="qb-trading-status", data=True),
            # FR-1.3：清空自选确认弹窗
            dbc.Modal(
                [
                    dbc.ModalHeader("确认清空自选"),
                    dbc.ModalBody("确定要清空所有自选标的吗？此操作不可撤销。"),
                    dbc.ModalFooter([
                        dbc.Button("取消", id="qb-clear-cancel", color="secondary", className="me-2"),
                        dbc.Button("确认清空", id="qb-clear-confirm", color="danger"),
                    ]),
                ],
                id="qb-clear-modal",
                is_open=False,
            ),
        ]
    )
