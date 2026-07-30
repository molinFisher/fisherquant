import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table


def create_strategy_center_layout():
    return dbc.Container(
        [
            html.H3("策略中心", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Button(
                                "新建策略", id="strategy-create-btn", color="primary", className="me-2"
                            ),
                            dbc.Button(
                                "导入策略", id="strategy-import-btn", color="secondary", className="me-2"
                            ),
                            dcc.Upload(
                                id="strategy-import-upload",
                                children=html.Div(),
                                style={"display": "none"},
                            ),
                            dcc.Download(id="strategy-export-download"),
                            html.Div(id="strategy-import-toast"),
                        ],
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.ButtonGroup(
                            [
                                dbc.Button(
                                    "SMA均线", id="template-sma", color="outline-secondary", size="sm"
                                ),
                                dbc.Button(
                                    "MACD", id="template-macd", color="outline-secondary", size="sm"
                                ),
                                dbc.Button(
                                    "Bollinger", id="template-bollinger", color="outline-secondary", size="sm"
                                ),
                                dbc.Button(
                                    "RSI", id="template-rsi", color="outline-secondary", size="sm"
                                ),
                                dbc.Button(
                                    "Buy&Hold", id="template-buyhold", color="outline-secondary", size="sm"
                                ),
                            ],
                            className="ms-2",
                        ),
                        width="auto",
                    ),
                ],
                className="mb-3 align-items-center",
            ),
            html.Div(id="strategy-table-container"),
        ]
    )


_STRATEGY_TYPES = [
    {"label": "均线交叉 (SMA Cross)", "value": "sma_cross"},
    {"label": "MACD", "value": "macd"},
    {"label": "布林带 (Bollinger)", "value": "bollinger"},
    {"label": "RSI", "value": "rsi"},
    {"label": "买入持有 (Buy & Hold)", "value": "buy_and_hold"},
    {"label": "自定义 (DSL)", "value": "custom"},
]


def _create_wizard_modal():
    """策略向导弹窗。提升到顶层布局（layout.create_layout 调用），确保始终存在于初始 DOM。

    之前该弹窗与依赖的 dcc.Store 随策略中心页面经 router 回调动态注入，
    在 Dash 4 下 dcc.Store 不会渲染到 DOM，导致向导回调写入失败 —— 弹窗打不开、
    「取消」按钮无效。

    关键修复点：向导导航回调 handle_wizard_navigation 以 wizard-name / wizard-type /
    wizard-description / wizard-symbols 作为 State，并以 wizard-prev-btn /
    wizard-next-btn / wizard-save-btn / wizard-cancel-btn 作为 Input。这些组件原本
    随步骤「条件渲染」—— 例如 step 0 没有「上一步/保存」按钮、step 2/3 没有 name/type/
    description 输入框。当在某步点击「取消」时，回调因缺少（当前步未渲染的）Input/State
    组件而整条失败，所有 Output（含 is_open=False）被丢弃，表现为取消无效。

    因此这里把以下组件设为弹窗「常驻」（始终在 DOM 中，仅按步骤显示/隐藏）：
      - wizard-name / wizard-type / wizard-description（步骤 0 显示）
      - wizard-symbols（步骤 2 显示）
      - 四个页脚按钮（始终渲染，不适用的禁用）
    对应显隐与回填由 strategy_wizard_callbacks.sync_wizard_fields 回调统一控制。
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(
                [
                    dbc.ModalTitle(id="strategy-wizard-title", children="新建策略"),
                ]
            ),
            dbc.ModalBody(id="strategy-wizard-body"),
            # 常驻基本信息字段：始终在 DOM，仅 step 0 显示（见 sync_wizard_fields）。
            html.Div(
                id="wizard-basic-fields",
                style={"display": "none"},
                children=[
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("策略名称"),
                                    dbc.Input(
                                        id="wizard-name",
                                        type="text",
                                        placeholder="输入策略名称...",
                                    ),
                                    html.Div(id="wizard-name-error", className="text-danger small mt-1"),
                                ],
                                width=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("策略类型"),
                                    dcc.Dropdown(
                                        id="wizard-type",
                                        options=_STRATEGY_TYPES,
                                        clearable=False,
                                        placeholder="选择策略类型...",
                                    ),
                                    html.Div(id="wizard-type-error", className="text-danger small mt-1"),
                                ],
                                width=6,
                            ),
                        ]
                    ),
                    dbc.Label("描述", className="mt-2"),
                    dbc.Textarea(id="wizard-description", placeholder="策略描述...", rows=3),
                ],
            ),
            # 常驻标的池下拉框：始终在 DOM，仅 step 2 显示（见 sync_wizard_fields）。
            dcc.Dropdown(
                id="wizard-symbols",
                multi=True,
                placeholder="选择标的（可选）...",
                style={"display": "none"},
            ),
            dbc.ModalFooter(id="strategy-wizard-footer"),
        ],
        id="strategy-wizard-modal",
        size="lg",
        is_open=False,
    )


def _render_wizard_step_0(prev_data=None):
    # 基本信息字段（wizard-name/type/description）已提升为弹窗常驻组件（见
    # _create_wizard_modal 的 wizard-basic-fields），仅在本步由 sync_wizard_fields
    # 回调显示并回填。此处不再重复渲染，避免重复 id 且该组件缺失导致向导回调整体失败。
    return dbc.Container(
        [
            html.H5("步骤 1/4: 基本信息", className="mb-3"),
            html.P("请填写策略名称与类型（描述可选）。", className="text-muted"),
        ]
    )


def _render_wizard_step_1(strategy_type, prev_data=None):
    data = prev_data or {}
    params = data.get("params", {})

    param_forms = {
        "sma_cross": [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("快线周期"),
                            dbc.Input(
                                id="param-fast",
                                type="number",
                                value=params.get("fast", 5),
                                min=1,
                                max=500,
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("慢线周期"),
                            dbc.Input(
                                id="param-slow",
                                type="number",
                                value=params.get("slow", 20),
                                min=2,
                                max=500,
                            ),
                        ],
                        width=6,
                    ),
                ]
            ),
        ],
        "macd": [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("快线周期"),
                            dbc.Input(
                                id="param-fast",
                                type="number",
                                value=params.get("fast", 12),
                                min=1,
                                max=500,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("慢线周期"),
                            dbc.Input(
                                id="param-slow",
                                type="number",
                                value=params.get("slow", 26),
                                min=2,
                                max=500,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("信号线周期"),
                            dbc.Input(
                                id="param-signal",
                                type="number",
                                value=params.get("signal", 9),
                                min=1,
                                max=500,
                            ),
                        ],
                        width=4,
                    ),
                ]
            ),
        ],
        "bollinger": [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("周期"),
                            dbc.Input(
                                id="param-period",
                                type="number",
                                value=params.get("period", 20),
                                min=1,
                                max=500,
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("标准差倍数"),
                            dbc.Input(
                                id="param-std",
                                type="number",
                                value=params.get("std", 2),
                                min=0.1,
                                max=10,
                                step=0.1,
                            ),
                        ],
                        width=6,
                    ),
                ]
            ),
        ],
        "rsi": [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("周期"),
                            dbc.Input(
                                id="param-period",
                                type="number",
                                value=params.get("period", 14),
                                min=2,
                                max=500,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("超买阈值"),
                            dbc.Input(
                                id="param-overbought",
                                type="number",
                                value=params.get("overbought", 70),
                                min=50,
                                max=100,
                            ),
                        ],
                        width=4,
                    ),
                    dbc.Col(
                        [
                            dbc.Label("超卖阈值"),
                            dbc.Input(
                                id="param-oversold",
                                type="number",
                                value=params.get("oversold", 30),
                                min=0,
                                max=50,
                            ),
                        ],
                        width=4,
                    ),
                ]
            ),
        ],
        "buy_and_hold": [
            html.P("买入持有策略无需参数配置", className="text-muted"),
        ],
        "custom": [
            dbc.Label("DSL配置 (JSON)"),
            dbc.Textarea(
                id="param-custom-dsl",
                value=params.get("dsl_config", "{}"),
                rows=12,
                style={"fontFamily": "monospace", "fontSize": "13px"},
            ),
            html.Div(id="wizard-dsl-validation", className="text-danger small mt-1"),
        ],
    }

    children = [html.H5("步骤 2/4: 参数配置", className="mb-3")]
    if strategy_type in param_forms:
        children.append(html.Div(param_forms[strategy_type]))
    else:
        children.append(html.P("请先选择策略类型", className="text-muted"))
    return dbc.Container(children)


def _render_wizard_step_2(prev_data=None):
    data = prev_data or {}
    # 注意：标的选择下拉框 wizard-symbols 已提升为弹窗常驻组件（见 layout._create_wizard_modal），
    # 仅在本步由 sync_symbols_ui 回调显示。此处不再重复渲染，避免重复 id 且该组件
    # 缺失导致向导回调整体失败。
    return dbc.Container(
        [
            html.H5("步骤 3/4: 标的池", className="mb-3"),
            html.P("选择需要应用策略的标的（留空则适用所有标的）", className="text-muted"),
        ]
    )


def _render_wizard_step_3(prev_data=None):
    data = prev_data or {}
    name = data.get("name", "未命名")
    stype = data.get("type", "未选择")
    params = data.get("params", {})
    symbols = data.get("symbols", [])
    description = data.get("description", "")

    type_labels = {t["value"]: t["label"] for t in _STRATEGY_TYPES}

    param_lines = []
    if params:
        for k, v in params.items():
            if k == "dsl_config":
                param_lines.append(html.Li(f"{k}: (自定义DSL)"))
            else:
                param_lines.append(html.Li(f"{k}: {v}"))
    else:
        param_lines.append(html.Li("无参数"))

    return dbc.Container(
        [
            html.H5("步骤 4/4: 确认创建", className="mb-3"),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H6(name, className="mb-2"),
                        html.P(
                            f"类型: {type_labels.get(stype, stype)}", className="mb-1"
                        ),
                        html.P(f"描述: {description or '无'}", className="mb-1 text-muted"),
                        html.P("参数:", className="mb-1"),
                        html.Ul(param_lines),
                        html.P(
                            f"标的池: {', '.join(symbols) if symbols else '全部标的'}",
                            className="mb-0",
                        ),
                    ]
                ),
                className="mb-3",
            ),
        ]
    )



