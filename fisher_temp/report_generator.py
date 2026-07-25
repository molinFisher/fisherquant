import json
from datetime import datetime
from pathlib import Path
from jinja2 import Template


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>FisherQuant Test Report</title>
<style>
body{font-family:monospace;max-width:900px;margin:40px auto;background:#0d1117;color:#c9d1d9}
h1{color:#58a6ff} h2{color:#f0883e} .pass{color:#3fb950} .fail{color:#f85149} .fix{color:#d2991d}
table{width:100%;border-collapse:collapse;margin:10px 0}
th,td{padding:6px 12px;text-align:left;border-bottom:1px solid #30363d}
th{background:#161b22}
</style></head>
<body>
<h1>FisherQuant Test Report</h1>
<p>Generated: {{ timestamp }}</p>

<h2>Summary</h2>
<table>
<tr><th>Phase</th><th>Status</th><th>Details</th></tr>
{% for phase in summary %}
<tr><td>{{ phase.name }}</td>
<td class="{{ 'pass' if phase.status == 'pass' else 'fail' }}">{{ phase.status }}</td>
<td>{{ phase.details }}</td></tr>
{% endfor %}
</table>

<h2>Unit Test Results</h2>
<p>Passed: <span class="pass">{{ unit.passed }}</span> |
   Failed: <span class="fail">{{ unit.failed }}</span> |
   Fixed: <span class="fix">{{ unit.fixed }}</span></p>

{% if unit.errors %}
<h3>Failures</h3>
<table>
<tr><th>Test</th><th>Type</th><th>Fixed</th><th>Description</th></tr>
{% for e in unit.errors %}
<tr><td>{{ e.test }}</td><td>{{ e.type }}</td>
<td class="{{ 'pass' if e.fixed else 'fail' }}">{{ 'Yes' if e.fixed else 'No' }}</td>
<td>{{ e.desc }}</td></tr>
{% endfor %}
</table>
{% endif %}

<h2>Backtest Results</h2>
{% for bt in backtests %}
<h3>{{ bt.name }}</h3>
<p>Tickers: {{ bt.tickers | join(', ') }} | Orders: {{ bt.orders }} | Status: {{ bt.status }}</p>
{% if bt.metrics %}
<p>Sharpe: {{ bt.metrics.get('sharpe_ratio', 'N/A') }} |
   Max DD: {{ bt.metrics.get('max_drawdown', 'N/A') }}</p>
{% endif %}
{% endfor %}

<h2>Fix Log</h2>
<table>
<tr><th>Error</th><th>Strategy</th><th>Fixed</th><th>Description</th></tr>
{% for fx in fix_log %}
<tr><td>{{ fx.error }}</td><td>{{ fx.strategy }}</td>
<td class="{{ 'pass' if fx.fixed else 'fail' }}">{{ fx.fixed }}</td>
<td>{{ fx.description }}</td></tr>
{% endfor %}
</table>

<h2>Auto-Fix Summary</h2>
<p>Total fixes applied: <span class="fix">{{ fix_count }}</span></p>
<p>Unresolved: <span class="fail">{{ unresolved }}</span></p>
</body>
</html>
"""


class ReportGenerator:
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, phase_results: dict) -> str:
        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")

        summary = [
            {"name": "Data Download", "status": "pass" if phase_results.get("data_ok") else "fail",
             "details": f"{phase_results.get('a_share_count', 0)} A-share, {phase_results.get('hk_count', 0)} HK"},
            {"name": "Unit Tests", "status": "pass" if phase_results.get("unit_failed", 0) == 0 else "fail",
             "details": f"{phase_results.get('unit_passed', 0)}/{phase_results.get('unit_total', 0)} passed"},
            {"name": "Backtest", "status": phase_results.get("backtest_status", "unknown"),
             "details": f"{phase_results.get('backtest_orders', 0)} orders"},
            {"name": "Monitor", "status": phase_results.get("monitor_status", "unknown"),
             "details": str(phase_results.get("monitor_results", {}))},
            {"name": "Auto-Fix", "status": "complete",
             "details": f"{phase_results.get('total_fixed', 0)} fixed, {phase_results.get('unresolved', 0)} unresolved"},
        ]

        context = {
            "timestamp": now,
            "summary": summary,
            "unit": {
                "passed": phase_results.get("unit_passed", 0),
                "failed": phase_results.get("unit_failed", 0),
                "fixed": phase_results.get("total_fixed", 0),
                "errors": phase_results.get("error_details", []),
            },
            "backtests": phase_results.get("backtest_details", []),
            "fix_log": phase_results.get("fix_details", []),
            "fix_count": phase_results.get("total_fixed", 0),
            "unresolved": phase_results.get("unresolved", 0),
        }

        template = Template(HTML_TEMPLATE)
        html = template.render(**context)

        html_path = self.output_dir / f"test_report_{now}.html"
        html_path.write_text(html, encoding="utf-8")

        json_path = self.output_dir / f"test_report_{now}.json"
        json_path.write_text(json.dumps(phase_results, indent=2, default=str), encoding="utf-8")

        return str(html_path)
