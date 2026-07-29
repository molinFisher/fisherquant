import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update, ctx
import logging

from fisher.dash_app.services.auto_load_service import (
    PHASE_IDLE, PHASE_LOADING, PHASE_PAUSED, PHASE_DONE, PHASE_ERROR,
)

logger = logging.getLogger(__name__)


def create_data_center_layout():
    return dbc.Container(
        [
            html.H3("数据中心", className="mb-3"),
            dbc.Tabs(
                [
                    dbc.Tab(label="数据查询", tab_id="tab-query", children=_create_query_tab()),
                    dbc.Tab(label="已缓存数据", tab_id="tab-cached", children=_create_cached_tab()),
                    dbc.Tab(label="高级功能", tab_id="tab-advanced", children=_create_advanced_tab()),
                    dbc.Tab(label="自动加载", tab_id="tab-auto-load", children=_create_auto_load_tab()),
                ],
                id="data-center-tabs",
                active_tab="tab-query",
                className="mb-3",
            ),
            dcc.Store(id="search-results-store"),
            dcc.Store(id="selected-symbols-store", data=[]),
            dcc.Store(id="toast-trigger"),
            dcc.Interval(id="auto-load-progress-poll", interval=3000),
            html.Div(id="data-center-content"),
        ]
    )


def _create_query_tab():
    return dbc.Row(
        [
            dbc.Col(
                [
                    dbc.Card(
                        [
                            dbc.CardHeader("标的搜索"),
                            dbc.CardBody(
                                [
                                    dbc.Input(
                                        id="symbol-search-input",
                                        type="text",
                                        placeholder="搜索名称/代码，或粘贴多代码（逗号/空格/换行分隔）",
                                        debounce=True,
                                    ),
                                    html.Div(id="search-status", className="text-muted small mt-1"),
                                    # FR-2/3：待选框（勾选式候选清单）+ 全选/反选工具条
                                    html.Div(
                                        [
                                            dbc.Button("全选", id="candidate-select-all-btn",
                                                       color="link", size="sm", className="p-0 me-3"),
                                            dbc.Button("反选", id="candidate-invert-btn",
                                                       color="link", size="sm", className="p-0"),
                                        ],
                                        className="mt-2 mb-1",
                                    ),
                                    html.Div(
                                        dbc.Checklist(
                                            id="candidate-list",
                                            options=[],
                                            value=[],
                                            className="small",
                                        ),
                                        style={"maxHeight": "320px", "overflowY": "auto"},
                                    ),
                                ]
                            ),
                        ],
                        className="mb-3",
                    ),
                    dbc.Card(
                        [
                            dbc.CardHeader("获取数据"),
                            dbc.CardBody(
                                [
                                    dbc.Label("时间范围"),
                                    dcc.DatePickerRange(
                                        id="date-range-picker",
                                        start_date="2024-01-01",
                                        end_date="2024-12-31",
                                        display_format="YYYY-MM-DD",
                                    ),
                                    dbc.Label("数据类型", className="mt-2"),
                                    dcc.RadioItems(
                                        id="data-type-radio",
                                        options=[
                                            {"label": "日线", "value": "daily"},
                                            {"label": "分钟线", "value": "minute"},
                                            {"label": "复权因子", "value": "adj"},
                                            {"label": "财务数据", "value": "financials"},
                                        ],
                                        value="daily",
                                    ),
                                    html.Div(
                                        id="minute-period-container",
                                        children=[
                                            dbc.Label("分钟周期", className="mt-2"),
                                            dcc.Dropdown(
                                                id="minute-period-selector",
                                                options=[
                                                    {"label": "1分钟", "value": "1min"},
                                                    {"label": "5分钟", "value": "5min"},
                                                    {"label": "15分钟", "value": "15min"},
                                                    {"label": "30分钟", "value": "30min"},
                                                    {"label": "60分钟", "value": "60min"},
                                                ],
                                                value="1min",
                                            ),
                                        ],
                                        style={"display": "none"},
                                    ),
                                    dbc.Button(
                                        "开始获取数据",
                                        id="fetch-data-button",
                                        color="primary",
                                        className="mt-2 w-100",
                                        disabled=True,
                                    ),
                                    # FR-5（数据获取稳定性）：保守模式开关——降速避免被数据源限流
                                    dbc.Checklist(
                                        options=[
                                            {"label": "保守模式（降速取数，降低被限流概率）", "value": "on"},
                                        ],
                                        value=[],
                                        id="fetch-conservative-switch",
                                        className="mt-2 small",
                                        switch=True,
                                    ),
                                    # FR-5：按钮不可用时常驻原因提示（DES-4）
                                    html.Div(id="fetch-guard-hint",
                                             className="text-muted small mt-1"),
                                    html.Div(id="fetch-status", className="mt-2"),
                                ]
                            ),
                        ]
                    ),
                ],
                width=6,
            ),
            dbc.Col(
                [
                    # FR-4：已选标的池（单一事实来源 selected-symbols-store，D2：取数结果不覆盖池）
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                html.Div(
                                    [
                                        html.Span("已选标的池"),
                                        dbc.Button("清空已选", id="clear-selected-btn",
                                                   color="link", size="sm",
                                                   className="p-0 float-end"),
                                    ]
                                )
                            ),
                            dbc.CardBody(id="selected-pool",
                                         children="尚未选择标的（从左侧搜索结果勾选）"),
                        ],
                        className="mb-3",
                    ),
                    dbc.Card(
                        [
                            dbc.CardHeader("获取结果"),
                            dbc.CardBody(id="fetch-results",
                                         children="取数结果将显示在这里"),
                        ]
                    ),
                ],
                width=6,
            ),
        ],
    )


def _create_auto_load_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("自动加载进度"),
                                dbc.CardBody(
                                    [
                                        html.Div(id="auto-load-progress-status", className="mb-2"),
                                        dbc.Progress(id="auto-load-progress-bar", value=0, label="0%",
                                                     className="mb-2", style={"height": "24px"}),
                                        html.Div(id="auto-load-progress-detail", className="text-muted small"),
                                        # 失败清单（FR-4.3 / U-3）：可展开，含「重试失败项」按钮（独立 id）
                                        dbc.Collapse(
                                            dbc.Card(
                                                dbc.CardBody(
                                                    [
                                                        html.Div("以下标的加载失败（可重试）：",
                                                                 className="small mb-2"),
                                                        dbc.ListGroup(id="auto-load-failed-list", flush=True),
                                                        dbc.Button(
                                                            "重试失败项", id="auto-load-retry-failed-btn",
                                                            color="warning", size="sm", className="mt-2",
                                                            style={"display": "none"}),
                                                    ]
                                                ),
                                                className="mt-2 border-danger",
                                            ),
                                            id="auto-load-failed-collapse", is_open=False,
                                        ),
                                    ]
                                ),
                            ],
                            className="mb-3",
                        ),
                        width=8,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader("控制"),
                                dbc.CardBody(
                                    [
                                        # 三态按钮：开始/继续（断点续传）/暂停/重新加载（二次确认）
                                        dbc.Button("开始自动加载", id="auto-load-start-btn",
                                                   color="primary", className="w-100 mb-2"),
                                        dbc.Button("继续", id="auto-load-resume-btn",
                                                   color="info", className="w-100 mb-2",
                                                   style={"display": "none"}),
                                        dbc.Button("暂停", id="auto-load-pause-btn",
                                                   color="warning", className="w-100 mb-2",
                                                   style={"display": "none"}),
                                        dbc.Button("重新加载", id="auto-load-reload-btn",
                                                   color="secondary", className="w-100 mb-2",
                                                   style={"display": "none"}),
                                        html.Div(id="auto-load-action-feedback", className="text-muted small mt-1"),
                                    ]
                                ),
                            ]
                        ),
                        width=4,
                    ),
                ]
            ),
            # 二次确认 Modal：「重新加载」会清空账本（保留历史数据）
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("确认重新加载？")),
                    dbc.ModalBody(
                        [
                            dbc.Checkbox(
                                id="auto-load-force-full-check",
                                label="彻底重下（忽略数据库已有历史，清空并全量重新下载）",
                                value=False, className="mb-2",
                            ),
                            "将清空当前加载账本并基于数据库已有历史数据重新规划（历史行情不会被删除）。"
                            "勾选「彻底重下」将忽略库存、全部标的重新下载。正在进行的加载会先暂停。",
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button("取消", id="auto-load-reload-cancel", color="secondary", className="me-2"),
                            dbc.Button("确认重新加载", id="auto-load-reload-confirm", color="primary"),
                        ]
                    ),
                ],
                id="auto-load-reload-modal",
                is_open=False,
            ),
        ]
    )


def _create_cached_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.InputGroup(
                                [
                                    dbc.Input(placeholder="筛选标的...", id="cache-filter-input"),
                                    dbc.Button("刷新", id="cache-refresh-btn", color="secondary"),
                                    # 删除范围：整行（全部类型）或仅某一数据类型（FR-1.5）
                                    dbc.Select(
                                        id="cache-delete-type",
                                        options=[
                                            {"label": "删除范围：全部类型", "value": "all"},
                                            {"label": "仅日线", "value": "daily"},
                                            {"label": "仅分钟线", "value": "minute"},
                                            {"label": "仅实时快照", "value": "realtime"},
                                            {"label": "仅复权因子", "value": "adj"},
                                            {"label": "仅财务数据", "value": "financials"},
                                        ],
                                        value="all",
                                        style={"maxWidth": "180px"},
                                    ),
                                    dbc.Button("删除选中", id="cache-delete-btn", color="danger"),
                                    dbc.Button("批量加入看板", id="cache-add-all-board-btn",
                                               color="success", outline=True),
                                ],
                                className="mb-2",
                            )
                        ],
                        width=12,
                    ),
                ]
            ),
            # U-3：市场与数据类型筛选并排一行（数据类型多选 = AND 语义）
            dbc.Row(
                [
                    dbc.Col(
                        dcc.RadioItems(
                            id="cache-market-filter",
                            options=[
                                {"label": "全部", "value": "all"},
                                {"label": "A股", "value": "a_share"},
                                {"label": "港股", "value": "hk_connect"},
                            ],
                            value="all",
                            inline=True,
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dcc.Checklist(
                            id="cache-type-filter",
                            options=[
                                {"label": " 日线", "value": "daily"},
                                {"label": " 分钟", "value": "minute"},
                                {"label": " 实时", "value": "realtime"},
                                {"label": " 复权", "value": "adj"},
                                {"label": " 财务", "value": "financials"},
                            ],
                            value=[],
                            inline=True,
                            inputStyle={"marginLeft": "12px"},
                        ),
                        width="auto",
                    ),
                ],
                className="mb-2 align-items-center",
            ),
            html.Div(id="cached-table-container"),
            # 删除二次确认 Modal（FR-8.3 / U-4：危险操作必须确认）
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("确认删除缓存数据")),
                    dbc.ModalBody(id="cache-delete-modal-body"),
                    dbc.ModalFooter(
                        [
                            dbc.Button("取消", id="cache-delete-cancel-btn",
                                       color="secondary", outline=True),
                            dbc.Button("确认删除", id="cache-delete-confirm-btn",
                                       color="danger"),
                        ]
                    ),
                ],
                id="cache-delete-modal",
                is_open=False,
                backdrop="static",
            ),
        ]
    )


def _derive_auto_load_progress(state: dict):
    """由 get_state() 推导进度面板（状态徽标/进度条/按钮可见性）。

    纯函数，可单测。关键修复：phase==LOADING 时一律显示「加载中」+ 暂停按钮，
    不再受 total 是否为 0 影响——避免「暂停按钮可见但左侧仍显示未运行」的 UI 不一致
    （V1.3 已知缺陷：resume_session 复用账本时不重写 total，total 偶为 0 触发旧分支）。
    """
    phase = state.get("phase", PHASE_IDLE)
    total = int(state.get("total", 0))
    done = int(state.get("done", 0))
    failed = int(state.get("failed", 0))
    pending = int(state.get("pending", 0))

    # 防御：未知/遗留阶段值一律安全降级为 idle，保证「开始」按钮始终可见
    if phase not in (PHASE_IDLE, PHASE_LOADING, PHASE_PAUSED, PHASE_DONE, PHASE_ERROR):
        phase = PHASE_IDLE

    show_start = {"display": "block" if phase in (PHASE_IDLE, PHASE_DONE, PHASE_ERROR) else "none"}
    show_resume = {"display": "block" if state.get("can_resume") else "none"}
    show_pause = {"display": "block" if phase == PHASE_LOADING else "none"}
    show_reload = {"display": "block" if phase in (PHASE_DONE, PHASE_PAUSED, PHASE_ERROR) else "none"}

    if phase == PHASE_LOADING:
        pct = int(done * 100 / total) if total > 0 else 0
        parts = []
        if done > 0:
            parts.append(f"已加载 {done}/{total}" if total > 0 else f"已加载 {done}")
        if failed > 0:
            parts.append(f"失败 {failed}")
        if pending > 0:
            parts.append(f"待处理 {pending}")
        detail = "，".join(parts) if parts else "正在准备加载任务..."
        label = f"{done}/{total} ({pct}%)" if total > 0 else f"{pct}%"
        return (dbc.Badge("加载中", color="info", className="me-2"),
                pct, label, detail,
                show_start, show_resume, show_pause, show_reload)
    if phase == PHASE_DONE and total > 0:
        if failed > 0:
            return (dbc.Badge("部分失败", color="danger", className="me-2"),
                    100, f"{done}/{total}",
                    f"成功 {done}，失败 {failed} 个（可展开清单重试）",
                    show_start, show_resume, show_pause, show_reload)
        return (dbc.Badge("已完成", color="success", className="me-2"),
                100, f"{total}/{total} (100%)",
                f"共处理 {total} 个标的（成功 {done}，失败 {failed}），数据就绪",
                show_start, show_resume, show_pause, show_reload)
    if phase == PHASE_PAUSED:
        return (dbc.Badge("已暂停", color="warning", className="me-2"),
                int(done * 100 / max(total, 1)), f"{done}/{total}",
                f"已暂停，可「继续」断点续传（待处理 {pending}）",
                show_start, show_resume, show_pause, show_reload)
    if phase == PHASE_ERROR:
        return (dbc.Badge("出错", color="danger", className="me-2"),
                0, "错误", state.get("message", "加载过程发生错误"),
                show_start, show_resume, show_pause, show_reload)
    # idle
    return (dbc.Badge("空闲", color="secondary", className="me-2"),
            0, "0%", "自动加载未运行，请点击「开始自动加载」",
            show_start, show_resume, show_pause, show_reload)


def register_data_center_callbacks(app):
    from fisher.dash_app.services import get_auto_load_service

    @app.callback(
        Output("auto-load-progress-status", "children"),
        Output("auto-load-progress-bar", "value"),
        Output("auto-load-progress-bar", "label"),
        Output("auto-load-progress-detail", "children"),
        Output("auto-load-start-btn", "style"),
        Output("auto-load-resume-btn", "style"),
        Output("auto-load-pause-btn", "style"),
        Output("auto-load-reload-btn", "style"),
        Input("auto-load-progress-poll", "n_intervals"),
    )
    def update_auto_load_progress(n):
        try:
            svc = get_auto_load_service()
            state = svc.get_state()
        except Exception as e:
            logger.error("auto-load progress check failed: %s", e)
            hidden = {"display": "none"}
            return "状态检查失败", 0, "0%", "", hidden, hidden, hidden, hidden
        return _derive_auto_load_progress(state)

    @app.callback(
        Output("auto-load-failed-collapse", "is_open"),
        Output("auto-load-failed-list", "children"),
        Output("auto-load-retry-failed-btn", "style"),
        Input("auto-load-progress-poll", "n_intervals"),
    )
    def update_auto_load_failed(n):
        """失败清单轮询（FR-4.3）：有最终失败则展开 Collapse 并渲染清单 + 显示重试按钮。"""
        try:
            svc = get_auto_load_service()
            state = svc.get_state()
            failed = svc.get_failed() if int(state.get("failed", 0)) > 0 else []
        except Exception as e:
            logger.error("auto-load failed-list check failed: %s", e)
            return False, [], {"display": "none"}
        if not failed:
            return False, [], {"display": "none"}
        items = [
            dbc.ListGroupItem(
                [
                    html.Span(f"{f['ticker']} {f['name']}", className="fw-bold"),
                    html.Span(f" · {f['reason']} · 已重试 {f['attempts']} 次",
                              className="text-muted small"),
                ]
            )
            for f in failed
        ]
        return True, items, {"display": "block"}

    @app.callback(
        Output("auto-load-reload-confirm", "children"),
        Output("auto-load-reload-confirm", "color"),
        Input("auto-load-force-full-check", "value"),
    )
    def update_reload_confirm_label(force_full):
        """「彻底重下」开关（#42）：勾选后确认按钮变红并提示全量重下。"""
        if force_full:
            return "清空并全量重下", "danger"
        return "确认重新加载", "primary"

    @app.callback(
        Output("auto-load-reload-modal", "is_open"),
        Input("auto-load-reload-btn", "n_clicks"),
        Input("auto-load-reload-cancel", "n_clicks"),
        Input("auto-load-reload-confirm", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_reload_modal(reload_clicks, cancel_clicks, confirm_clicks):
        if not ctx.triggered:
            return no_update
        tid = ctx.triggered[0]["prop_id"].split(".")[0]
        if tid == "auto-load-reload-btn":
            return True
        return False

    @app.callback(
        Output("auto-load-action-feedback", "children"),
        Input("auto-load-start-btn", "n_clicks"),
        Input("auto-load-resume-btn", "n_clicks"),
        Input("auto-load-pause-btn", "n_clicks"),
        Input("auto-load-reload-confirm", "n_clicks"),
        Input("auto-load-retry-failed-btn", "n_clicks"),
        State("auto-load-force-full-check", "value"),
        prevent_initial_call=True,
    )
    def handle_auto_load_action(start_clicks, resume_clicks, pause_clicks,
                                reload_confirm_clicks, retry_failed_clicks, force_full):
        if not ctx.triggered:
            return no_update
        tid = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            svc = get_auto_load_service()
            if tid == "auto-load-start-btn":
                svc.start()
                return "自动加载已启动（基于数据库已有历史数据规划），请查看进度..."
            if tid == "auto-load-resume-btn":
                svc.resume_session()
                return "已从断点继续加载..."
            if tid == "auto-load-pause-btn":
                svc.pause()
                return "自动加载已暂停，可稍后「继续」"
            if tid == "auto-load-reload-confirm":
                svc.reload(force_full=bool(force_full))
                return ("已触发彻底重下（全量重新下载），请查看进度..."
                        if force_full else "已重新规划加载（历史数据保留），请查看进度...")
            if tid == "auto-load-retry-failed-btn":
                svc.retry_failed()
                return "正在重试失败项..."
        except Exception as e:
            logger.exception("auto-load action failed")
            return f"操作失败: {e}"


def _create_advanced_tab():
    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("自动刷新设置"),
                                    dbc.CardBody(
                                        [
                                            dbc.Checkbox(
                                                id="auto-refresh-toggle",
                                                label="启用自动刷新",
                                                value=False,
                                            ),
                                            dbc.Input(
                                                id="auto-refresh-cron",
                                                placeholder="cron表达式，例如: 0 16 * * 1-5",
                                                className="mt-2",
                                            ),
                                            html.Div(id="next-refresh-time", className="text-muted small mt-1"),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                        ],
                        width=6,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader("数据导出"),
                                    dbc.CardBody(
                                        [
                                            dcc.Dropdown(
                                                id="export-format-dropdown",
                                                options=[
                                                    {"label": "CSV", "value": "csv"},
                                                    {"label": "Excel", "value": "xlsx"},
                                                    {"label": "Parquet", "value": "parquet"},
                                                ],
                                                value="csv",
                                                placeholder="选择导出格式",
                                            ),
                                            dbc.Label("筛选标的（可选，逗号分隔）", className="mt-2"),
                                            dbc.Input(
                                                id="export-symbol-input",
                                                placeholder="如: 600519.SH, 000001.SZ",
                                                className="mb-1",
                                            ),
                                            dbc.Row([
                                                dbc.Col([
                                                    dbc.Label("起始日期"),
                                                    dcc.DatePickerSingle(id="export-start-date", date=""),
                                                ]),
                                                dbc.Col([
                                                    dbc.Label("截止日期"),
                                                    dcc.DatePickerSingle(id="export-end-date", date=""),
                                                ]),
                                            ], className="mb-1"),
                                            dbc.Button(
                                                "导出数据",
                                                id="export-data-btn",
                                                color="primary",
                                                className="mt-2 w-100",
                                            ),
                                            dcc.Download(id="download-data"),
                                        ]
                                    ),
                                ],
                                className="mb-3",
                            ),
                            dbc.Card(
                                [
                                    dbc.CardHeader("复权因子"),
                                    dbc.CardBody(
                                        [
                                            dbc.Input(
                                                id="adj-factor-symbol",
                                                placeholder="输入标的代码",
                                                className="mb-2",
                                            ),
                                            dbc.Button(
                                                "查询复权因子",
                                                id="fetch-adj-factor-btn",
                                                color="info",
                                                className="w-100",
                                            ),
                                            html.Div(id="adj-factor-result", className="mt-2"),
                                        ]
                                    ),
                                ],
                            ),
                        ],
                        width=6,
                    ),
                ]
            ),
        ]
    )
