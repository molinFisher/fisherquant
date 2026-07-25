import json
from pathlib import Path
from datetime import datetime

import dash
from dash import Input, Output, State, callback, no_update, html, dcc
import dash_bootstrap_components as dbc
from jinja2 import Template

from fisher.backtest.serializer import BacktestSerializer
from fisher.analytics.performance import (
    cumulative_return, annualized_return, sharpe_ratio, max_drawdown, daily_returns,
)
from fisher.store.engine import DuckDBManager

REPORT_HTML_TEMPLATE = Template("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FisherQuant 回测报告</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #212529; }
        h1 { color: #0d6efd; border-bottom: 2px solid #0d6efd; padding-bottom: 8px; }
        h2 { color: #495057; margin-top: 30px; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }
        th { background-color: #f8f9fa; }
        .positive { color: #198754; }
        .negative { color: #dc3545; }
        .metric-card { display: inline-block; width: 180px; padding: 15px; margin: 10px; background: #f8f9fa; border-radius: 8px; text-align: center; }
        .metric-value { font-size: 24px; font-weight: bold; }
        .section-toggle { margin: 0 10px; }
    </style>
</head>
<body>
    <h1>FisherQuant 回测报告</h1>
    <p><strong>策略:</strong> {{ metadata.strategy }}</p>
    <p><strong>回测区间:</strong> {{ metadata.start_date }} 至 {{ metadata.end_date }}</p>
    <p><strong>生成时间:</strong> {{ generated_at }}</p>

    {% if "equity" in sections %}
    <h2>净值曲线</h2>
    <p>初始净值: 1.0000 | 最终净值: {{ "%.4f"|format(nav[-1]) if nav else "N/A" }}</p>
    {% endif %}

    {% if "performance" in sections %}
    <h2>绩效指标</h2>
    <div>
        <div class="metric-card"><div class="metric-label">累计收益</div><div class="metric-value {{ 'positive' if total_return > 0 else 'negative' }}">{{ "%.2f%%"|format(total_return*100) }}</div></div>
        <div class="metric-card"><div class="metric-label">年化收益</div><div class="metric-value {{ 'positive' if ann_return > 0 else 'negative' }}">{{ "%.2f%%"|format(ann_return*100) }}</div></div>
        <div class="metric-card"><div class="metric-label">Sharpe</div><div class="metric-value">{{ "%.2f"|format(sharpe) }}</div></div>
        <div class="metric-card"><div class="metric-label">最大回撤</div><div class="metric-value negative">{{ "%.2f%%"|format(max_dd*100) }}</div></div>
    </div>
    {% endif %}

    {% if "trades" in sections %}
    <h2>交易记录</h2>
    <table>
        <tr><th>标的</th><th>方向</th><th>数量</th><th>价格</th><th>佣金</th></tr>
        {% for t in trades[:50] %}
        <tr><td>{{ t.ticker }}</td><td class="{{ 'positive' if t.side=='buy' else 'negative' }}">{{ '买入' if t.side=='buy' else '卖出' }}</td><td>{{ t.quantity }}</td><td>{{ "%.2f"|format(t.price) }}</td><td>{{ "%.4f"|format(t.commission) }}</td></tr>
        {% endfor %}
    </table>
    {% endif %}

    {% if "drawdown" in sections %}
    <h2>回撤分析</h2>
    <p>最大回撤: <span class="negative">{{ "%.2f%%"|format(max_dd*100) }}</span></p>
    {% endif %}

    <p style="text-align: center; color: #6c757d; margin-top: 30px;">FisherQuant 报告自动生成</p>
</body>
</html>
""")


def register_report_callbacks(app):
    @app.callback(
        Output("report-progress-bar", "value"),
        Output("report-status-text", "children"),
        Output("report-preview-iframe", "srcDoc"),
        Input("report-preview-btn", "n_clicks"),
        State("report-backtest-id-input", "value"),
        State("report-sections-checklist", "value"),
        prevent_initial_call=True,
    )
    def preview_report(n_clicks, backtest_id, sections):
        if not backtest_id:
            return 0, "请输入回测ID", "<p>请输入回测ID</p>"
        html_content = _generate_report(backtest_id, sections or [])
        if html_content is None:
            return 0, "加载失败", "<p>回测数据加载失败</p>"
        return 100, "预览已生成", html_content

    @app.callback(
        Output("report-download", "data"),
        Input("report-generate-btn", "n_clicks"),
        State("report-backtest-id-input", "value"),
        State("report-format-radio", "value"),
        State("report-sections-checklist", "value"),
        prevent_initial_call=True,
    )
    def download_report(n_clicks, backtest_id, fmt, sections):
        if not backtest_id:
            return no_update

        html_content = _generate_report(backtest_id, sections or [])
        if html_content is None:
            return no_update

        if fmt == "pdf":
            try:
                import weasyprint
                import io
                pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
                return dcc.send_bytes(pdf_bytes, filename=f"backtest_{backtest_id}.pdf")
            except ImportError:
                return dcc.send_string(html_content, filename=f"backtest_{backtest_id}.html")
        else:
            return dcc.send_string(html_content, filename=f"backtest_{backtest_id}.html")


def _generate_report(backtest_id, sections):
    try:
        serializer = BacktestSerializer()
        data = serializer.load(backtest_id)
    except Exception:
        return None

    if not data or "equity" not in data:
        return None

    nav = data.get("equity", [])
    trades = data.get("trades", [])
    metadata = data.get("metadata", {})

    total_ret = cumulative_return(nav)
    ann_ret = annualized_return(nav)
    sharpe = sharpe_ratio(nav)
    mdd = max_drawdown(nav)

    html = REPORT_HTML_TEMPLATE.render(
        nav=nav,
        trades=trades,
        metadata=metadata,
        sections=sections,
        total_return=total_ret,
        ann_return=ann_ret,
        sharpe=sharpe,
        max_dd=mdd,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return html
