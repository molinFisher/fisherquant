import dash_bootstrap_components as dbc
from dash import html, dcc

NAV_ITEMS = [
    {
        "group": "数据管理",
        "items": [
            {"id": "data-center", "label": "数据中心", "icon": "📥"},
            {"id": "market-watch", "label": "行情看板", "icon": "📈"},
        ],
    },
    {
        "group": "策略研究",
        "items": [
            {"id": "strategy-center", "label": "策略中心", "icon": "🧠"},
            {"id": "factor-center", "label": "因子计算", "icon": "🔬"},
            {"id": "backtest-center", "label": "回测中心", "icon": "⚡"},
        ],
    },
    {
        "group": "结果分析",
        "items": [
            {"id": "visual-dashboard", "label": "可视化看板", "icon": "📊"},
            {"id": "report-center", "label": "报告中心", "icon": "📄"},
        ],
    },
    {
        "group": "系统",
        "items": [
            {"id": "settings", "label": "系统设置", "icon": "⚙️"},
        ],
    },
]


def create_sidebar():
    nav_groups = []
    for i, group in enumerate(NAV_ITEMS):
        items = []
        for item in group["items"]:
            items.append(
                dbc.NavLink(
                    [html.Span(item["icon"], className="me-2"), item["label"]],
                    href=f"/{item['id']}",
                    id={"type": "nav-item", "index": item["id"]},
                    className="nav-item",
                    active="exact",
                )
            )
        group_id = f"nav-group-{i}"
        collapse_id = f"nav-group-collapse-{i}"
        nav_groups.append(
            html.Div(
                [
                    html.Div(
                        group["group"],
                        className="nav-group-title",
                        id=group_id,
                        n_clicks=0,
                        **{"data-bs-toggle": "collapse", "data-bs-target": f"#{collapse_id}"},
                    ),
                    dbc.Collapse(
                        html.Div(items, className="nav-group-items"),
                        id=collapse_id,
                        is_open=True,
                    ),
                ],
                className="nav-group",
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.H4("FisherQuant", className="text-white mb-0"),
                    html.Small("量化交易系统", className="text-muted"),
                ],
                className="sidebar-brand",
            ),
            html.Hr(className="border-secondary"),
            dbc.Nav(nav_groups, vertical=True, pills=True, className="sidebar-nav"),
            html.Div(
                [
                    html.Hr(className="border-secondary"),
                    dbc.Button(
                        [html.Span("⚙️", className="me-1"), "设置"],
                        href="/settings",
                        color="link",
                        size="sm",
                        className="text-muted sidebar-settings-btn",
                    ),
                ],
                className="sidebar-footer",
            ),
        ],
        className="sidebar",
    )


def create_mobile_header():
    return html.Div(
        [
            dbc.Button(
                html.Span("☰", className="hamburger-icon"),
                id="sidebar-toggle-btn",
                color="link",
                className="sidebar-toggle d-md-none",
            ),
            html.Span("FisherQuant", className="mobile-brand d-md-none"),
        ],
        className="mobile-header",
    )


def create_layout():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            create_mobile_header(),
                            html.Div(
                                create_sidebar(),
                                id="sidebar-wrapper",
                                className="sidebar-wrapper",
                            ),
                        ],
                        width=2,
                        className="sidebar-col g-0",
                        id="sidebar-container",
                    ),
                    dbc.Col(
                        html.Div(id="page-content"),
                        width=10,
                        className="content-col",
                        id="content-container",
                    ),
                ],
                className="g-0 main-row",
            ),
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="session-store", storage_type="session"),
            dcc.Store(id="backtest-results", storage_type="session"),
            dcc.Store(id="sidebar-state", data={"open": True}),
            dcc.Interval(id="refresh-interval", interval=60000),
            html.Div(id="toast-container", className="toast-container"),
        ],
        fluid=True,
        className="app-container",
    )
