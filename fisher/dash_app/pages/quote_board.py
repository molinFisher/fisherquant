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
                            dbc.Checkbox(id="qb-auto-refresh-toggle", label="自动刷新(60s)", value=True, className="d-inline-block"),
                        ],
                        width=6,
                        className="text-end",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            html.Div(id="qb-table-container"),
            dcc.Store(id="qb-watchlist-store", data=[]),
            dcc.Interval(id="qb-refresh-interval", interval=60000, disabled=False),
            dcc.Store(id="qb-trading-status", data=True),
        ]
    )
