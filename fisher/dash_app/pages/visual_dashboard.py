import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table
import polars as pl


def create_visual_dashboard_layout():
    return dbc.Container(
        [
            html.H3("可视化看板", className="mb-3"),
            dcc.Location(id="viz-url", refresh=False),
            html.Div(id="viz-loading-container", children='请输入回测ID或在回测中心点击"查看完整看板"'),
            dcc.Store(id="viz-backtest-data", data=None),
            dcc.Store(id="viz-backtest-id", data=None),
            _create_viz_content_container(),
        ]
    )


def _create_viz_content_container():
    return html.Div(
        id="viz-content",
        style={"display": "none"},
        children=[
            dbc.Tabs(
                [
                    dbc.Tab(label="净值曲线", tab_id="tab-equity", children=[
                        html.Div(id="viz-equity-chart", className="mt-3"),
                    ]),
                    dbc.Tab(label="回撤分析", tab_id="tab-drawdown", children=[
                        html.Div(id="viz-drawdown-chart", className="mt-3"),
                    ]),
                    dbc.Tab(label="月度热力图", tab_id="tab-heatmap", children=[
                        html.Div(id="viz-monthly-heatmap", className="mt-3"),
                    ]),
                    dbc.Tab(label="收益分布", tab_id="tab-histogram", children=[
                        html.Div(id="viz-return-histogram", className="mt-3"),
                    ]),
                    dbc.Tab(label="交易记录", tab_id="tab-trades", children=[
                        html.Div(id="viz-trade-log", className="mt-3"),
                    ]),
                    dbc.Tab(label="K线图", tab_id="tab-kline", children=[
                        dbc.Row(
                            [
                                dbc.Col(
                                    dcc.Dropdown(
                                        id="viz-kline-symbol",
                                        options=[],
                                        placeholder="选择标的...",
                                        clearable=False,
                                    ),
                                    width=3,
                                ),
                            ],
                            className="mt-2 mb-2",
                        ),
                        html.Div(id="viz-kline-chart"),
                    ]),
                ],
                id="viz-tabs",
                active_tab="tab-equity",
                className="mb-3",
            ),
        ],
    )


def _build_equity_chart(nav, benchmark_nav):
    import plotly.graph_objects as go
    from fisher.visualization.downsample import lttb

    sampled_nav = lttb([(i, nav[i]) for i in range(len(nav))], 500)
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=[p[0] for p in sampled_nav],
        y=[p[1] for p in sampled_nav],
        mode="lines",
        name="策略净值",
        line=dict(color="#0d6efd", width=2),
    ))

    if benchmark_nav and len(benchmark_nav) > 1:
        min_len = min(len(nav), len(benchmark_nav))
        b_nav = benchmark_nav[:min_len]
        sampled_bench = lttb([(i, b_nav[i]) for i in range(len(b_nav))], 500)
        fig.add_trace(go.Scatter(
            x=[p[0] for p in sampled_bench],
            y=[p[1] for p in sampled_bench],
            mode="lines",
            name="基准净值",
            line=dict(color="#6c757d", width=1.5, dash="dash"),
        ))

    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Bar Index",
        yaxis_title="Net Value",
        hovermode="x unified",
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": True})


def _build_drawdown_chart(nav):
    import plotly.graph_objects as go

    dd = [0.0]
    peak = nav[0] if nav else 1.0
    for n in nav[1:]:
        if n > peak:
            peak = n
        dd.append((peak - n) / peak if peak > 0 else 0.0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(dd))),
        y=[-d for d in dd],
        fill="tozeroy",
        fillcolor="rgba(220,53,69,0.3)",
        mode="lines",
        line=dict(color="#dc3545", width=1),
        name="回撤",
    ))
    fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Bar Index",
        yaxis_title="Drawdown",
        yaxis_tickformat=".1%",
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": True})


def _build_monthly_heatmap(daily_rets):
    import plotly.graph_objects as go
    import math

    months = []
    values = []
    positions = []
    labels = []

    pos = 0
    month_data = {}
    for i, ret in enumerate(daily_rets):
        month_idx = i // 21
        if month_idx not in month_data:
            month_data[month_idx] = []
        month_data[month_idx].append(ret)

    for month_idx in sorted(month_data.keys()):
        rets = month_data[month_idx]
        if not rets:
            continue
        monthly_ret = 1.0
        for r in rets:
            monthly_ret *= (1 + r)
        monthly_ret -= 1
        values.append(monthly_ret)
        months.append(f"M{month_idx + 1}")
        year = month_idx // 12
        col = month_idx % 12
        positions.append([year, col])

    if not values:
        return html.Div("无收益数据", className="text-muted")

    max_val = max(abs(min(values)), abs(max(values))) or 1

    z = [[0.0] * 12 for _ in range(max(p[0] for p in positions) + 1)]
    for i, (r, c) in enumerate(positions):
        if i < len(values):
            z[r][c] = values[i]

    z_flat = [[z[r][c] for c in range(12)] for r in range(len(z))]

    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        z=z_flat,
        x=[f"{m+1}月" for m in range(12)],
        y=[f"第{r+1}年" for r in range(len(z))],
        colorscale=[[0, "#dc3545"], [0.5, "#ffffff"], [1, "#198754"]],
        zmid=0,
        text=[[f"{z[r][c]*100:.1f}%" for c in range(12)] for r in range(len(z))],
        texttemplate="%{text}",
        hovertemplate="%{y} %{x}<br>收益: %{z:.2%}",
    ))
    fig.update_layout(
        height=400, margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": True})


def _build_return_histogram(daily_rets):
    import plotly.graph_objects as go
    import math

    if not daily_rets:
        return html.Div("无收益数据", className="text-muted")

    mean_ret = sum(daily_rets) / len(daily_rets)
    var_ret = sum((r - mean_ret) ** 2 for r in daily_rets) / len(daily_rets)
    std_ret = math.sqrt(var_ret)

    x_range = list(range(-int(len(daily_rets) / 10), int(len(daily_rets) / 10)))
    normal_y = []
    for i in range(len(x_range)):
        n = len(daily_rets)
        x = i / n * 0.1
        normal_y.append(
            (1 / (std_ret * math.sqrt(2 * math.pi))) *
            math.exp(-0.5 * ((x - mean_ret) / std_ret) ** 2) if std_ret > 0 else 0
        )

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=daily_rets, nbinsx=50,
        name="实际分布",
        marker_color="#0d6efd",
        opacity=0.7,
        histnorm="probability density",
    ))
    fig.add_trace(go.Scatter(
        x=[mean_ret + (i - 25) * std_ret / 5 for i in range(51)],
        y=[(1 / (std_ret * 2.5066)) * math.exp(-0.5 * ((mean_ret + (i - 25) * std_ret / 5 - mean_ret) / std_ret) ** 2)
           if std_ret > 0 else 0 for i in range(51)],
        mode="lines",
        name="正态分布",
        line=dict(color="#dc3545", width=2),
    ))
    fig.update_layout(
        height=350, margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="日收益率", yaxis_title="频率",
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": True})


def _build_trade_log(trades):
    if not trades:
        return html.Div("无交易记录", className="text-muted")

    columns = [
        {"name": "时间", "id": "timestamp"},
        {"name": "标的", "id": "ticker"},
        {"name": "方向", "id": "side"},
        {"name": "数量", "id": "quantity"},
        {"name": "价格", "id": "price"},
        {"name": "佣金", "id": "commission"},
    ]

    data = []
    for t in trades:
        side = "买入" if t.get("side") == "buy" else "卖出"
        side_color = "#198754" if side == "买入" else "#dc3545"
        data.append({
            "timestamp": str(t.get("timestamp", "")),
            "ticker": t.get("ticker", ""),
            "side": side,
            "quantity": t.get("quantity", 0),
            "price": f"{t.get('price', 0):.2f}",
            "commission": f"{t.get('commission', 0):.4f}",
        })

    return dash_table.DataTable(
        columns=columns,
        data=data,
        page_size=20,
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell={"padding": "6px", "fontSize": "12px"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": "{side} = '买入'", "column_id": "side"},
             "color": "#198754", "fontWeight": "bold"},
            {"if": {"filter_query": "{side} = '卖出'", "column_id": "side"},
             "color": "#dc3545", "fontWeight": "bold"},
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
        ],
    )


def _build_kline_chart(bars_df, trades, symbol):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from fisher.visualization.downsample import lttb

    if bars_df is None or len(bars_df) == 0:
        return html.Div("无K线数据", className="text-muted")

    symbol_bars = bars_df.filter(pl.col("ticker") == symbol) if symbol is not None else bars_df
    if len(symbol_bars) == 0:
        return html.Div(f"无标的 {symbol} 的数据", className="text-muted")

    symbol_bars = symbol_bars.sort("bar_time" if "bar_time" in symbol_bars.columns else "trade_date")

    dates = list(range(len(symbol_bars)))
    opens = symbol_bars["open"].to_list()
    highs = symbol_bars["high"].to_list()
    lows = symbol_bars["low"].to_list()
    closes = symbol_bars["close"].to_list()

    if len(dates) > 500:
        indices = []
        step = len(dates) / 500
        for k in range(500):
            indices.append(int(k * step))
        if indices[-1] != len(dates) - 1:
            indices.append(len(dates) - 1)
        dates = [dates[i] for i in indices]
        opens = [opens[i] for i in indices]
        highs = [highs[i] for i in indices]
        lows = [lows[i] for i in indices]
        closes = [closes[i] for i in indices]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
    )

    fig.add_trace(
        go.Candlestick(
            x=dates, open=opens, high=highs, low=lows, close=closes,
            name="K线",
            increasing=dict(line=dict(color="#dc3545"), fillcolor="#dc3545"),
            decreasing=dict(line=dict(color="#198754"), fillcolor="#198754"),
        ),
        row=1, col=1,
    )

    if len(closes) >= 20:
        ma20 = []
        for i in range(len(closes)):
            if i >= 19:
                ma20.append(sum(closes[i - 19:i + 1]) / 20)
            else:
                ma20.append(None)
        fig.add_trace(go.Scatter(
            x=dates, y=ma20, mode="lines",
            name="MA20", line=dict(color="#6f42c1", width=1),
        ), row=1, col=1)

    if len(closes) >= 60:
        ma60 = []
        for i in range(len(closes)):
            if i >= 59:
                ma60.append(sum(closes[i - 59:i + 1]) / 60)
            else:
                ma60.append(None)
        fig.add_trace(go.Scatter(
            x=dates, y=ma60, mode="lines",
            name="MA60", line=dict(color="#fd7e14", width=1),
        ), row=1, col=1)

    if trades:
        buy_x, buy_y = [], []
        sell_x, sell_y = [], []
        for i, t in enumerate(trades):
            side = t.get("side", "")
            price = t.get("price", 0)
            if isinstance(price, (int, float)) and price > 0:
                bar_idx = min(i + 10, len(dates) - 1)
                if side == "buy":
                    buy_x.append(bar_idx)
                    buy_y.append(price)
                elif side == "sell":
                    sell_x.append(bar_idx)
                    sell_y.append(price)

        if buy_x:
            fig.add_trace(go.Scatter(
                x=buy_x, y=buy_y, mode="markers",
                marker=dict(color="#dc3545", symbol="triangle-up", size=10),
                name="买入"),
                row=1, col=1,
            )
        if sell_x:
            fig.add_trace(go.Scatter(
                x=sell_x, y=sell_y, mode="markers",
                marker=dict(color="#198754", symbol="triangle-down", size=10),
                name="卖出"),
                row=1, col=1,
            )

    volumes = symbol_bars["volume"].to_list() if len(dates) == len(symbol_bars["volume"].to_list()) else symbol_bars["volume"].to_list()[:len(dates)]
    if len(volumes) > len(dates):
        volumes = volumes[:len(dates)]

    colors = []
    for i in range(len(closes)):
        if i == 0:
            colors.append("#dc3545" if closes[i] >= opens[i] else "#198754")
        else:
            colors.append("#dc3545" if closes[i] >= closes[i - 1] else "#198754")

    fig.add_trace(
        go.Bar(x=dates, y=volumes, name="成交量", marker=dict(color=colors, opacity=0.5)),
        row=2, col=1,
    )

    fig.update_layout(
        height=500, margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(title_text="", row=2, col=1)
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)

    return dcc.Graph(figure=fig, config={"displayModeBar": True})
