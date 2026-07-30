import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table

from fisher.factor.registry import FactorRegistry
from fisher.factor import register_all_factors


def _registered_names() -> set:
    """返回已注册（可实现）因子名集合；调用前确保注册（幂等）。"""
    register_all_factors()
    return {f.name for f in FactorRegistry.list_all()}


def _factor_options() -> list:
    """计算下拉选项：未实现因子 disabled。"""
    registered = _registered_names()
    return [
        {
            "label": f"{f['name']} - {f['description']}",
            "value": f["name"],
            "disabled": f["name"] not in registered,
        }
        for f in FACTOR_DEFINITIONS
    ]


def create_factor_center_layout():
    return dbc.Container(
        [
            html.H3("因子计算中心", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="因子列表", tab_id="tab-factor-list", children=_create_factor_list_tab()),
                    dbc.Tab(label="因子计算", tab_id="tab-factor-compute", children=_create_factor_compute_tab()),
                    dbc.Tab(label="数据预览", tab_id="tab-factor-preview", children=_create_factor_preview_tab()),
                ],
                id="factor-center-tabs",
                active_tab="tab-factor-list",
                className="mb-3",
            ),
            dcc.Store(id="factor-compute-result-store"),
        ]
    )


FACTOR_DEFINITIONS = [
    {"name": "sma_5", "category": "均线", "description": "5日均线", "default_params": {"window": 5}},
    {"name": "sma_10", "category": "均线", "description": "10日均线", "default_params": {"window": 10}},
    {"name": "sma_20", "category": "均线", "description": "20日均线", "default_params": {"window": 20}},
    {"name": "sma_60", "category": "均线", "description": "60日均线", "default_params": {"window": 60}},
    {"name": "ema_12", "category": "均线", "description": "12日指数移动平均", "default_params": {"window": 12}},
    {"name": "ema_26", "category": "均线", "description": "26日指数移动平均", "default_params": {"window": 26}},
    {"name": "macd", "category": "技术指标", "description": "MACD指标 (DIF/DEA/柱)", "default_params": {}},
    {"name": "rsi_14", "category": "技术指标", "description": "14日RSI (相对强弱指标)", "default_params": {}},
    {"name": "bollinger", "category": "技术指标", "description": "布林带 (中轨/上轨/下轨)", "default_params": {}},
    {"name": "atr", "category": "波动率", "description": "平均真实波幅 (ATR)", "default_params": {"period": 14}},
    {"name": "volume_sma", "category": "成交量", "description": "成交量均线", "default_params": {"window": 20}},
    {"name": "momentum_20d", "category": "动量", "description": "20日动量", "default_params": {}},
    {"name": "momentum_60d", "category": "动量", "description": "60日动量", "default_params": {}},
    {"name": "volatility_20d", "category": "波动率", "description": "20日波动率", "default_params": {}},
    {"name": "volatility_60d", "category": "波动率", "description": "60日波动率", "default_params": {}},
    {"name": "volume_ratio", "category": "成交量", "description": "量比 (成交量/5日均量)", "default_params": {}},
    {"name": "turnover_5d", "category": "成交量", "description": "5日平均换手", "default_params": {}},
    {"name": "turnover_20d", "category": "成交量", "description": "20日平均换手", "default_params": {}},
]


def _create_factor_list_tab():
    registered = _registered_names()
    columns = [
        {"name": "因子名称", "id": "name"},
        {"name": "类别", "id": "category"},
        {"name": "描述", "id": "description"},
        {"name": "状态", "id": "status"},
    ]
    data = []
    for f in FACTOR_DEFINITIONS:
        is_impl = f["name"] in registered
        data.append({
            "name": f["name"],
            "category": f["category"],
            "description": f["description"],
            "status": "可用" if is_impl else "未实现",
        })

    style_data_conditional = [
        {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
    ]
    # 未实现因子行灰显
    for i, f in enumerate(FACTOR_DEFINITIONS):
        if f["name"] not in registered:
            style_data_conditional.append(
                {"if": {"row_index": i}, "color": "#adb5bd", "fontStyle": "italic"}
            )

    return dbc.Container(
        [
            html.H5("可用因子列表", className="mb-3"),
            dash_table.DataTable(
                id="factor-list-table",
                columns=columns,
                data=data,
                page_size=20,
                style_table={"overflowX": "auto"},
                style_cell={"padding": "8px", "fontSize": "13px"},
                style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
                style_data_conditional=style_data_conditional,
            ),
        ]
    )


def _create_factor_compute_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("选择标的"),
                                dbc.CardBody(
                                    [
                                        dcc.Dropdown(
                                            id="factor-compute-symbols",
                                            options=[],
                                            multi=True,
                                            placeholder="选择要计算因子的标的...",
                                        ),
                                        html.Div(id="factor-compute-symbol-count", className="text-muted small mt-1"),
                                    ]
                                ),
                            ],
                            className="mb-3",
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("选择因子"),
                                dbc.CardBody(
                                    [
                                        dcc.Dropdown(
                                            id="factor-compute-factors",
                                            options=_factor_options(),
                                            multi=True,
                                            placeholder="选择要计算的因子...",
                                        ),
                                        html.Div(id="factor-compute-factor-count", className="text-muted small mt-1"),
                                    ]
                                ),
                            ],
                            className="mb-3",
                        ),
                        width=6,
                    ),
                ]
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("数据频率"),
                                dbc.CardBody(
                                    dcc.Dropdown(
                                        id="factor-compute-frequency",
                                        options=[
                                            {"label": "日线", "value": "daily"},
                                            {"label": "1 分钟", "value": "1"},
                                            {"label": "5 分钟", "value": "5"},
                                            {"label": "15 分钟", "value": "15"},
                                            {"label": "30 分钟", "value": "30"},
                                            {"label": "60 分钟", "value": "60"},
                                        ],
                                        value="daily",
                                        clearable=False,
                                    )
                                ),
                            ],
                            className="mb-3",
                        ),
                        width=6,
                    ),
                ],
                className="mb-2",
            ),
            dbc.Button(
                "开始计算",
                id="factor-compute-btn",
                color="primary",
                className="mb-2",
            ),
            dbc.Progress(
                id="factor-compute-progress",
                value=0,
                label="0%",
                className="mb-2",
                style={"height": "4px"},
            ),
            html.Div(id="factor-compute-status"),
        ]
    )


def _create_factor_preview_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("选择标的"),
                                    dbc.CardBody(
                                        dcc.Dropdown(
                                            id="factor-preview-symbol",
                                            options=[],
                                            placeholder="选择标的查看因子数据...",
                                            clearable=True,
                                        )
                                    ),
                                ],
                                className="mb-3",
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("因子统计"),
                                    dbc.CardBody(id="factor-preview-stats", children="请选择标的"),
                                ],
                                className="mb-3",
                            ),
                        ],
                        width=8,
                    ),
                ]
            ),
            html.Div(id="factor-preview-table-container"),
        ]
    )
