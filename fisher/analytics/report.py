import json
from pathlib import Path
from jinja2 import Environment, BaseLoader, Template

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FisherQuant Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; color: #333; }
        table { border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 8px 16px; text-align: right; }
        th { background: #f5f5f5; }
        h1 { color: #1a1a2e; }
        h2 { color: #16213e; margin-top: 30px; }
        .positive { color: green; }
        .negative { color: red; }
    </style>
</head>
<body>
    <h1>FisherQuant Performance Report</h1>
    <h2>Performance Metrics</h2>
    <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Metric</th><th>Value</th></tr>
        {% for key, value in metrics.items() %}
        <tr><td>{{ key.replace('_', ' ').title() }}</td><td>{{ "%.4f"|format(value) if value is float else value }}</td></tr>
        {% endfor %}
    </table>
    {% if attribution %}
    <h2>Brinson Attribution</h2>
    <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Component</th><th>Value</th></tr>
        {% for key in ['allocation_effect', 'selection_effect', 'interaction_effect', 'total_excess_return'] %}
        <tr><td>{{ key.replace('_', ' ').title() }}</td><td>{{ "%.4f"|format(attribution.get(key, 0.0)) }}</td></tr>
        {% endfor %}
    </table>
    {% endif %}
</body>
</html>"""

_env = Environment(loader=BaseLoader())
_template: Template = _env.from_string(_REPORT_TEMPLATE)


def report_to_json(
    metrics: dict[str, float],
    attribution: dict | None = None,
) -> str:
    report = {"metrics": metrics}
    if attribution:
        report["attribution"] = attribution
    return json.dumps(report, indent=2, default=str)


def report_to_html(
    metrics: dict[str, float],
    attribution: dict | None = None,
) -> str:
    return _template.render(metrics=metrics, attribution=attribution or {})
