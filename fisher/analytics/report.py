import json


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
    metrics_rows = ""
    for key, value in metrics.items():
        label = key.replace("_", " ").title()
        if isinstance(value, float):
            formatted = f"{value:.4f}"
        else:
            formatted = str(value)
        metrics_rows += f"<tr><td>{label}</td><td>{formatted}</td></tr>"

    attribution_html = ""
    if attribution:
        attr_rows = ""
        for key in ["allocation_effect", "selection_effect", "interaction_effect", "total_excess_return"]:
            label = key.replace("_", " ").title()
            value = attribution.get(key, 0.0)
            attr_rows += f"<tr><td>{label}</td><td>{value:.4f}</td></tr>"

        attribution_html = f"""
        <h2>Brinson Attribution</h2>
        <table border="1" cellpadding="6" cellspacing="0">
            <tr><th>Component</th><th>Value</th></tr>
            {attr_rows}
        </table>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FisherQuant Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; color: #333; }}
        table {{ border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 8px 16px; text-align: right; }}
        th {{ background: #f5f5f5; }}
        h1 {{ color: #1a1a2e; }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
    </style>
</head>
<body>
    <h1>FisherQuant Performance Report</h1>
    <h2>Performance Metrics</h2>
    <table border="1" cellpadding="6" cellspacing="0">
        <tr><th>Metric</th><th>Value</th></tr>
        {metrics_rows}
    </table>
    {attribution_html}
</body>
</html>"""
    return html
