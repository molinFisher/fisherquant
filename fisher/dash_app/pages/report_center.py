import dash_bootstrap_components as dbc
from dash import html, dcc


def create_report_center_layout():
    return dbc.Container(
        [
            html.H3("报告中心", className="mb-3"),
            dbc.Row(
                [
                    dbc.Col(_create_report_config_panel(), width=4),
                    dbc.Col(_create_report_preview_panel(), width=8),
                ]
            ),
            dcc.Store(id="report-backtest-id"),
            dcc.Download(id="report-download"),
        ]
    )


def _create_report_config_panel():
    return dbc.Card(
        [
            dbc.CardHeader("报告配置"),
            dbc.CardBody(
                [
                    dbc.Label("回测ID"),
                    dbc.Input(id="report-backtest-id-input", placeholder="输入回测ID..."),
                    dbc.Label("报告格式", className="mt-2"),
                    dcc.RadioItems(
                        id="report-format-radio",
                        options=[
                            {"label": "HTML", "value": "html"},
                            {"label": "PDF", "value": "pdf"},
                        ],
                        value="html",
                        inline=True,
                    ),
                    dbc.Label("报告模块", className="mt-3"),
                    dbc.Checklist(
                        id="report-sections-checklist",
                        options=[
                            {"label": "净值曲线", "value": "equity"},
                            {"label": "绩效指标", "value": "performance"},
                            {"label": "交易记录", "value": "trades"},
                            {"label": "K线图", "value": "kline"},
                            {"label": "回撤分析", "value": "drawdown"},
                            {"label": "月度收益", "value": "monthly"},
                        ],
                        value=["equity", "performance", "trades", "drawdown"],
                        inline=False,
                    ),
                    dbc.Button("生成报告", id="report-generate-btn", color="primary", className="mt-3 w-100"),
                    dbc.Button("预览", id="report-preview-btn", color="info", className="mt-2 w-100"),
                    dbc.Progress(id="report-progress-bar", value=0, className="mt-2", style={"height": "4px"}),
                    html.Div(id="report-status-text", className="text-muted small mt-1"),
                ]
            ),
        ]
    )


def _create_report_preview_panel():
    return dbc.Card(
        [
            dbc.CardHeader("报告预览"),
            dbc.CardBody(
                [
                    html.Iframe(
                        id="report-preview-iframe",
                        style={"width": "100%", "height": "600px", "border": "1px solid #dee2e6", "borderRadius": "4px"},
                        srcDoc="<p>请配置并点击"预览"</p>",
                    ),
                ]
            ),
        ]
    )
