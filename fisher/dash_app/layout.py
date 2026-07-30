import dash_bootstrap_components as dbc
from dash import html, dcc

from fisher.dash_app.pages.strategy_center import _create_wizard_modal

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

    # 首页：常驻顶部（不在折叠分组内），与现有 nav-item 样式/高亮一致
    home_link = dbc.NavLink(
        [html.Span("🏠", className="me-2"), "首页"],
        href="/home",
        id={"type": "nav-item", "index": "home"},
        className="nav-item",
        active="exact",
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
            dbc.Nav(
                [home_link, html.Hr(className="border-secondary")] + nav_groups,
                vertical=True, pills=True, className="sidebar-nav",
            ),
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
            # 策略中心向导弹窗与状态存储：提升到顶层布局，始终存在于初始 DOM。
            # 若随策略中心页面经 router 回调动态注入，dcc.Store 在 Dash 4 下不会
            # 渲染到 DOM，导致向导回调（打开/取消/保存）写入失败、弹窗与
            # 「取消」按钮失效。详见 _create_wizard_modal 注释。
            _create_wizard_modal(),
            dcc.Store(id="strategy-wizard-state", data={"step": 0}),
            dcc.Store(id="strategy-list-store"),
            dcc.Store(id="strategy-edit-id"),
            dcc.Store(id="strategy-refresh-trigger", data=""),
            dcc.Store(id="confirm-delete-strategy-name", data=""),
            dcc.Store(id="symbol-pool-options-store"),
        ],
        fluid=True,
        className="app-container",
    )
