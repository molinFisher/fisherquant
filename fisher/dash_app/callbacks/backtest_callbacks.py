import json
import uuid
import asyncio
import os
from datetime import datetime
from pathlib import Path

import dash
from dash import Input, Output, State, callback, no_update, html, dcc, ctx
import dash_bootstrap_components as dbc
import polars as pl

from fisher.store.engine import DuckDBManager
from fisher.backtest.engine import BacktestEngine
from fisher.backtest.serializer import BacktestSerializer
from fisher.paper.engine import PaperEngine
from fisher.position.service import PositionService
from fisher.strategy.execution import create_strategy
from fisher.analytics.performance import (
    cumulative_return, annualized_return, sharpe_ratio, max_drawdown,
)
from fisher.visualization.downsample import lttb
from fisher.config.schemas import AssetFeeConfig
from fisher.event.types import Bar

STRATEGIES_DIR = Path("strategies")


def _load_strategies():
    strategies = []
    if not STRATEGIES_DIR.exists():
        return strategies
    for f in sorted(STRATEGIES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("enabled", True):
                strategies.append(data)
        except (json.JSONDecodeError, IOError):
            continue
    return strategies


def _get_cached_symbols():
    try:
        db = DuckDBManager()
        if not db._initialized:
            db_path = "./data/fisherquant.db"
            try:
                db.connect(db_path, read_pool_size=4)
            except Exception:
                pass
        df = db.query_df("SELECT DISTINCT ticker FROM bars_daily ORDER BY ticker")
        return [{"label": r[0], "value": r[0]} for r in df.iter_rows()]
    except Exception:
        return []


def _load_bars(symbol, start_date, end_date):
    db = DuckDBManager()
    if not db._initialized:
        try:
            db.connect("./data/fisherquant.db", read_pool_size=4)
        except Exception:
            pass
    try:
        df = db.query_df(
            "SELECT ticker, trade_date, open, high, low, close, volume, amount, market "
            "FROM bars_daily WHERE ticker=? AND trade_date BETWEEN ? AND ? "
            "ORDER BY trade_date",
            [symbol, start_date, end_date],
        )
        return df
    except Exception:
        return pl.DataFrame()


def _bars_df_to_bars(df, symbol):
    bars = []
    for row in df.iter_rows():
        bars.append(
            Bar(
                ticker=row[0],
                market=row[8] if len(row) > 8 else "a_share",
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                volume=int(row[6] or 0),
                amount=float(row[7] or 0),
                bar_time=0.0,
            )
        )
    return bars


def _load_benchmark_nav(benchmark_ticker, start_date, end_date, nav_len):
    if benchmark_ticker == "none":
        return None
    db = DuckDBManager()
    if not db._initialized:
        try:
            db.connect("./data/fisherquant.db", read_pool_size=4)
        except Exception:
            pass
    try:
        df = db.query_df(
            "SELECT close FROM bars_daily WHERE ticker=? AND trade_date BETWEEN ? AND ? "
            "ORDER BY trade_date",
            [benchmark_ticker, start_date, end_date],
        )
        if len(df) == 0:
            return None
        closes = df["close"].to_list()
        return _compute_benchmark_nav(closes, nav_len)
    except Exception:
        pass
    return None


def _compute_benchmark_nav(closes, nav_len):
    if not closes or len(closes) < 2:
        return None
    nav = [1.0]
    for i in range(1, len(closes)):
        nav.append(nav[-1] * (closes[i] / closes[i - 1]))
    while len(nav) < nav_len:
        nav.append(nav[-1])
    return nav[:nav_len]


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


_CANCEL_FLAGS: dict[str, bool] = {}


def _build_summary(nav, trades, benchmark_nav):
    total_ret = cumulative_return(nav)
    ann_ret = annualized_return(nav)
    sharpe = sharpe_ratio(nav)
    mdd = max_drawdown(nav)

    total_ret_str = f"{total_ret * 100:.2f}%"
    ann_ret_str = f"{ann_ret * 100:.2f}%"
    color_ret = "text-success" if total_ret > 0 else "text-danger"

    trade_count = len(trades) if trades else 0
    buy_trades = sum(1 for t in trades if t.get("side") == "buy") if trades else 0
    sell_trades = trade_count - buy_trades if trades else 0

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("累计收益", className="text-muted small"),
                                    html.H4(total_ret_str, className=color_ret),
                                ]
                            ),
                            className="stat-card",
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("年化收益", className="text-muted small"),
                                    html.H4(ann_ret_str, className=color_ret),
                                ]
                            ),
                            className="stat-card",
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("Sharpe", className="text-muted small"),
                                    html.H4(f"{sharpe:.2f}", className="text-primary"),
                                ]
                            ),
                            className="stat-card",
                        ),
                        width=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("最大回撤", className="text-muted small"),
                                    html.H4(f"{mdd * 100:.2f}%", className="text-danger"),
                                ]
                            ),
                            className="stat-card",
                        ),
                        width=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("交易次数", className="text-muted small"),
                                    html.H4(f"{trade_count}", className="text-info"),
                                    html.Small(f"买{buy_trades} / 卖{sell_trades}", className="text-muted"),
                                ]
                            ),
                            className="stat-card",
                        ),
                        width=2,
                    ),
                ],
                className="mb-3",
            ),
            html.Hr(),
        ]
    )


def _build_equity_thumbnail(nav):
    if len(nav) < 2:
        return html.Div()
    points = [(i, nav[i]) for i in range(len(nav))]
    sampled = lttb(points, 300)
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p[0] for p in sampled],
            y=[p[1] for p in sampled],
            mode="lines",
            name="策略净值",
            line=dict(color="#0d6efd", width=1.5),
        )
    )
    fig.update_layout(
        height=200,
        margin=dict(l=10, r=10, t=5, b=5),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def register_backtest_callbacks(app):
    @app.callback(
        Output("bt-strategy-dropdown", "options"),
        Output("bt-symbol-select", "options"),
        Input("url", "pathname"),
    )
    def load_config_options(pathname):
        strategies = _load_strategies()
        strategy_options = [
            {"label": s.get("name", ""), "value": json.dumps(s)}
            for s in strategies
        ]
        symbols = _get_cached_symbols()
        return strategy_options, symbols

    @app.callback(
        Output("bt-progress-bar", "value"),
        Output("bt-progress-bar", "label"),
        Output("bt-progress-text", "children"),
        Output("bt-summary-container", "children"),
        Output("bt-equity-thumbnail", "children"),
        Output("bt-results-link", "children"),
        Output("bt-run-btn", "disabled"),
        Output("bt-run-btn", "style"),
        Output("bt-cancel-btn", "style"),
        Output("bt-submitting", "data"),
        Output("bt-cancel-flag", "data"),
        Input("bt-run-btn", "n_clicks"),
        Input("bt-cancel-btn", "n_clicks"),
        State("bt-strategy-dropdown", "value"),
        State("bt-symbol-select", "value"),
        State("bt-date-range", "start_date"),
        State("bt-date-range", "end_date"),
        State("bt-capital", "value"),
        State("bt-commission", "value"),
        State("bt-slippage", "value"),
        State("bt-benchmark", "value"),
        State("bt-submitting", "data"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("bt-run-btn", "disabled"), True, False),
            (Output("bt-cancel-btn", "style"), {"display": "block"}, {"display": "none"}),
            (Output("bt-progress-bar", "value"), 0, 100),
        ],
    )
    def run_backtest(run_clicks, cancel_clicks, strategy_json, symbols,
                     start_date, end_date, capital, commission, slippage,
                     benchmark_ticker, is_submitting):
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        if triggered_id == "bt-cancel-btn":
            _CANCEL_FLAGS["current"] = True
            return (
                0, "已取消", "回测已取消",
                html.Div("回测已取消", className="text-warning"),
                html.Div(), html.Div(),
                False, {}, {"display": "none"},
                False, False,
            )

        if not strategy_json:
            return (
                0, "0%", "请先选择策略",
                html.Div("请先选择策略", className="text-warning"),
                html.Div(), html.Div(),
                False, {}, {"display": "none"},
                False, False,
            )

        _CANCEL_FLAGS["current"] = False

        try:
            strategy_config = json.loads(strategy_json)
        except json.JSONDecodeError:
            return (
                0, "0%", "策略配置解析失败",
                html.Div("策略配置解析失败", className="text-danger"),
                html.Div(), html.Div(),
                False, {}, {"display": "none"},
                False, False,
            )

        target_symbols = symbols if symbols else [s["value"] for s in _get_cached_symbols()]
        if not target_symbols:
            return (
                0, "0%", "无可用标的",
                html.Div("无可用标的，请先获取数据", className="text-warning"),
                html.Div(), html.Div(),
                False, {}, {"display": "none"},
                False, False,
            )

        commission_pct = (commission or 0.025) / 100.0
        initial_capital = capital or 1000000.0

        fee_cfg = AssetFeeConfig(
            commission_rate=commission_pct,
            min_commission=5.0,
        )

        strategy_name = strategy_config.get("name", "unnamed")
        paper = PaperEngine(fee_config=fee_cfg, initial_capital=initial_capital)
        positions = PositionService()

        all_bars = []
        for symbol in target_symbols:
            if _CANCEL_FLAGS.get("current"):
                return (
                    0, "已取消", "回测已取消",
                    html.Div("回测已取消", className="text-warning"),
                    html.Div(), html.Div(),
                    False, {}, {"display": "none"},
                    False, False,
                )
            df = _load_bars(symbol, start_date, end_date)
            if len(df) == 0:
                continue
            for row in df.iter_rows():
                all_bars.append(
                    Bar(
                        ticker=row[0],
                        market=row[8] if len(row) > 8 else "a_share",
                        open=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        close=float(row[5]),
                        volume=int(row[6] or 0),
                        amount=float(row[7] or 0),
                        bar_time=0.0,
                    )
                )

        if not all_bars:
            return (
                100, "100%", "无有效数据",
                html.Div("无法加载数据，请检查标的和日期范围", className="text-warning"),
                html.Div(), html.Div(),
                False, {}, {"display": "none"},
                False, False,
            )

        bars_pl = pl.DataFrame([{
            "ticker": b.ticker,
            "bar_time": float(b.bar_time),
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "amount": b.amount,
            "market": b.market,
        } for b in all_bars])

        strategy = create_strategy(strategy_config)

        engine = BacktestEngine(
            bars_df=bars_pl,
            paper_engine=paper,
            position_service=positions,
        )

        result = _run_async(engine.run(strategy))

        nav = result["nav_history"]
        trades = result["trades"]

        benchmark_nav = None
        if benchmark_ticker and benchmark_ticker != "none":
            b_df = _load_bars(benchmark_ticker, start_date, end_date)
            if len(b_df) > 0:
                b_closes = b_df["close"].to_list()
                benchmark_nav = _compute_benchmark_nav(b_closes, len(nav))

        result_id = str(uuid.uuid4())[:8]
        total_ret = cumulative_return(nav)
        sharpe = sharpe_ratio(nav)
        mdd = max_drawdown(nav)

        serializer = BacktestSerializer()
        serializer.save(
            result_id=result_id,
            nav_history=nav,
            trades=trades,
            benchmark=benchmark_nav,
            metadata={
                "strategy": strategy_name,
                "symbols": target_symbols[:5],
                "start_date": start_date,
                "end_date": end_date,
                "capital": initial_capital,
                "commission": commission_pct,
                "total_return": total_ret,
                "sharpe": sharpe,
                "max_drawdown": mdd,
            },
        )
        serializer.cleanup(keep=200)

        summary = _build_summary(nav, trades, benchmark_nav)
        thumbnail = _build_equity_thumbnail(nav)
        link = html.A(
            dbc.Button("查看完整看板", color="info", size="sm"),
            href=f"/visual-dashboard?backtest_id={result_id}",
            target="_blank",
        )

        return (
            100, "100%", "回测完成",
            summary, thumbnail, link,
            False, {}, {"display": "none"},
            False, False,
        )

    @app.callback(
        Output("bt-run-btn", "disabled", allow_duplicate=True),
        Input("bt-run-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def prevent_double_click(n):
        return True

    @app.callback(
        Output("bt-cancel-flag", "data", allow_duplicate=True),
        Input("bt-cancel-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def set_cancel_flag(n):
        _CANCEL_FLAGS["current"] = True
        return True

    @app.callback(
        Output("bt-multi-strategies", "options"),
        Input("url", "pathname"),
    )
    def load_multi_strategies(pathname):
        strategies = _load_strategies()
        return [{"label": s.get("name", ""), "value": json.dumps(s)} for s in strategies]

    @app.callback(
        Output("bt-multi-symbols", "options"),
        Input("url", "pathname"),
    )
    def load_multi_symbols(pathname):
        return _get_cached_symbols()

    @app.callback(
        Output("bt-multi-results", "children"),
        Input("bt-multi-run-btn", "n_clicks"),
        State("bt-multi-strategies", "value"),
        State("bt-multi-symbols", "value"),
        State("bt-multi-date-range", "start_date"),
        State("bt-multi-date-range", "end_date"),
        State("bt-multi-capital", "value"),
        State("bt-multi-commission", "value"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("bt-multi-run-btn", "disabled"), True, False),
        ],
    )
    def run_multi_compare(n_clicks, strategy_jsons, symbols, start_date, end_date,
                          capital, commission):
        if not strategy_jsons or len(strategy_jsons) < 2:
            return html.Div("请至少选择2个策略", className="text-warning")

        if len(strategy_jsons) > 5:
            strategy_jsons = strategy_jsons[:5]

        target_symbols = symbols if symbols else [s["value"] for s in _get_cached_symbols()]
        if not target_symbols:
            return html.Div("无可用标的", className="text-warning")

        commission_pct = (commission or 0.025) / 100.0
        initial_capital = capital or 1000000.0

        results = {}
        for sj in strategy_jsons:
            try:
                sc = json.loads(sj)
            except json.JSONDecodeError:
                continue
            name = sc.get("name", "unknown")
            paper = PaperEngine(
                fee_config=AssetFeeConfig(commission_rate=commission_pct, min_commission=5.0),
                initial_capital=initial_capital,
            )
            positions = PositionService()
            all_bars = []
            for sym in target_symbols[:3]:
                df = _load_bars(sym, start_date, end_date)
                if len(df) == 0:
                    continue
                for row in df.iter_rows():
                    all_bars.append(Bar(
                        ticker=row[0], market=row[8] if len(row) > 8 else "a_share",
                        open=float(row[2]), high=float(row[3]), low=float(row[4]),
                        close=float(row[5]), volume=int(row[6] or 0),
                        amount=float(row[7] or 0), bar_time=0.0,
                    ))
            if not all_bars:
                continue
            bars_pl = pl.DataFrame([{
                "ticker": b.ticker, "bar_time": float(b.bar_time),
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume, "amount": b.amount,
                "market": b.market,
            } for b in all_bars])
            strategy = create_strategy(sc)
            engine = BacktestEngine(bars_df=bars_pl, paper_engine=paper, position_service=positions)
            res = _run_async(engine.run(strategy))
            nav = res["nav_history"]
            total_ret = cumulative_return(nav)
            sharpe = sharpe_ratio(nav)
            mdd = max_drawdown(nav)
            results[name] = {
                "nav": nav,
                "total_return": total_ret,
                "sharpe": sharpe,
                "max_drawdown": mdd,
            }

        if not results:
            return html.Div("回测失败，无有效数据", className="text-danger")

        best_ret = max(r["total_return"] for r in results.values())
        best_sharpe = max(r["sharpe"] for r in results.values())
        best_mdd = min(r["max_drawdown"] for r in results.values())

        table_header = html.Tr([
            html.Th("策略"), html.Th("累计收益"), html.Th("Sharpe"), html.Th("最大回撤")
        ])
        table_rows = [table_header]
        for name, r in results.items():
            ret_cls = "text-success" if r["total_return"] == best_ret else ""
            sharp_cls = "text-success" if r["sharpe"] == best_sharpe else ""
            mdd_cls = "text-success" if r["max_drawdown"] == best_mdd else ""
            table_rows.append(html.Tr([
                html.Td(name),
                html.Td(f"{r['total_return']*100:.2f}%", className=ret_cls),
                html.Td(f"{r['sharpe']:.2f}", className=sharp_cls),
                html.Td(f"{r['max_drawdown']*100:.2f}%", className=mdd_cls),
            ]))

        import plotly.graph_objects as go
        fig = go.Figure()
        colors = ["#0d6efd", "#dc3545", "#198754", "#ffc107", "#6f42c1"]
        for i, (name, r) in enumerate(results.items()):
            nav = r["nav"]
            sampled = lttb([(j, nav[j]) for j in range(len(nav))], 300)
            fig.add_trace(go.Scatter(
                x=[p[0] for p in sampled], y=[p[1] for p in sampled],
                mode="lines", name=name,
                line=dict(color=colors[i % len(colors)], width=1.5),
            ))
        fig.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )

        return html.Div([
            html.H6("绩效对比", className="mb-2"),
            html.Table(table_rows, className="table table-sm table-hover"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ])

    @app.callback(
        Output("bt-wf-strategy", "options"),
        Input("url", "pathname"),
    )
    def load_wf_strategies(pathname):
        strategies = _load_strategies()
        return [{"label": s.get("name", ""), "value": json.dumps(s)} for s in strategies]

    @app.callback(
        Output("bt-wf-results", "children"),
        Input("bt-wf-run-btn", "n_clicks"),
        State("bt-wf-strategy", "value"),
        State("bt-wf-windows", "value"),
        State("bt-wf-date-range", "start_date"),
        State("bt-wf-date-range", "end_date"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("bt-wf-run-btn", "disabled"), True, False),
        ],
    )
    def run_walkforward(n_clicks, strategy_json, window_count, start_date, end_date):
        if not strategy_json:
            return html.Div("请选择策略", className="text-warning")

        window_count = max(4, min(24, window_count or 8))
        try:
            sc = json.loads(strategy_json)
        except json.JSONDecodeError:
            return html.Div("策略配置解析失败", className="text-danger")

        symbols = [s["value"] for s in _get_cached_symbols()]
        if not symbols:
            return html.Div("无可用标的", className="text-warning")

        from datetime import datetime as dt, timedelta
        sdate = dt.strptime(start_date, "%Y-%m-%d")
        edate = dt.strptime(end_date, "%Y-%m-%d")
        total_days = (edate - sdate).days
        window_days = total_days // window_count

        window_results = []
        for w in range(window_count):
            w_start = sdate + timedelta(days=w * window_days)
            w_end = min(sdate + timedelta(days=(w + 1) * window_days), edate)
            w_start_str = w_start.strftime("%Y-%m-%d")
            w_end_str = w_end.strftime("%Y-%m-%d")

            paper = PaperEngine(initial_capital=1000000.0)
            positions = PositionService()
            all_bars = []
            for sym in symbols[:3]:
                df = _load_bars(sym, w_start_str, w_end_str)
                if len(df) == 0:
                    continue
                for row in df.iter_rows():
                    all_bars.append(Bar(
                        ticker=row[0], market=row[8] if len(row) > 8 else "a_share",
                        open=float(row[2]), high=float(row[3]), low=float(row[4]),
                        close=float(row[5]), volume=int(row[6] or 0),
                        amount=float(row[7] or 0), bar_time=0.0,
                    ))
            if not all_bars:
                continue
            bars_pl = pl.DataFrame([{
                "ticker": b.ticker, "bar_time": float(b.bar_time),
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume, "amount": b.amount,
                "market": b.market,
            } for b in all_bars])
            strategy = create_strategy(sc)
            engine = BacktestEngine(bars_df=bars_pl, paper_engine=paper, position_service=positions)
            res = _run_async(engine.run(strategy))
            nav = res["nav_history"]
            window_results.append({
                "window": w + 1,
                "start": w_start_str,
                "end": w_end_str,
                "return": cumulative_return(nav),
                "sharpe": sharpe_ratio(nav),
                "max_dd": max_drawdown(nav),
            })

        if not window_results:
            return html.Div("回测失败", className="text-danger")

        returns = [wr["return"] for wr in window_results]
        sharpes = [wr["sharpe"] for wr in window_results]
        avg_ret = sum(returns) / len(returns)
        avg_sharpe = sum(sharpes) / len(sharpes)

        table_rows = [html.Tr([html.Th("窗口"), html.Th("起始"), html.Th("结束"),
                               html.Th("收益"), html.Th("Sharpe"), html.Th("最大回撤")])]
        for wr in window_results:
            ret_cls = "text-success" if wr["return"] > 0 else "text-danger"
            table_rows.append(html.Tr([
                html.Td(str(wr["window"])),
                html.Td(wr["start"]),
                html.Td(wr["end"]),
                html.Td(f"{wr['return']*100:.2f}%", className=ret_cls),
                html.Td(f"{wr['sharpe']:.2f}"),
                html.Td(f"{wr['max_dd']*100:.2f}%"),
            ]))

        agg_color = "text-success" if avg_ret > 0 else "text-danger"
        return html.Div([
            html.H6(f"滚动优化结果 ({window_count}窗口)", className="mb-2"),
            html.Table(table_rows, className="table table-sm table-hover"),
            html.Hr(),
            html.P([
                html.Strong("汇总: "),
                html.Span(f"平均收益: {avg_ret*100:.2f}%  |  ", className=agg_color),
                html.Span(f"平均Sharpe: {avg_sharpe:.2f}"),
            ]),
        ])

    @app.callback(
        Output("bt-sens-strategy", "options"),
        Output("bt-sens-param1", "options"),
        Output("bt-sens-param2", "options"),
        Input("url", "pathname"),
    )
    def load_sens_strategies(pathname):
        strategies = _load_strategies()
        strategy_options = [{"label": s.get("name", ""), "value": json.dumps(s)} for s in strategies]
        param_keys = {"fast": "快线", "slow": "慢线", "signal": "信号线",
                      "period": "周期", "std": "标准差", "overbought": "超买", "oversold": "超卖"}
        param1_options = [{"label": v, "value": k} for k, v in param_keys.items()]
        param2_options = [{"label": "无", "value": ""}] + param1_options
        return strategy_options, param1_options, param2_options

    @app.callback(
        Output("bt-sens-results", "children"),
        Input("bt-sens-run-btn", "n_clicks"),
        State("bt-sens-strategy", "value"),
        State("bt-sens-param1", "value"),
        State("bt-sens-min1", "value"),
        State("bt-sens-max1", "value"),
        State("bt-sens-step1", "value"),
        State("bt-sens-param2", "value"),
        State("bt-sens-min2", "value"),
        State("bt-sens-max2", "value"),
        State("bt-sens-step2", "value"),
        State("bt-sens-date-range", "start_date"),
        State("bt-sens-date-range", "end_date"),
        prevent_initial_call=True,
        background=True,
        running=[
            (Output("bt-sens-run-btn", "disabled"), True, False),
        ],
    )
    def run_sensitivity(n_clicks, strategy_json, param1, min1, max1, step1,
                        param2, min2, max2, step2, start_date, end_date):
        if not strategy_json or not param1:
            return html.Div("请选择策略和参数", className="text-warning")

        try:
            sc = json.loads(strategy_json)
        except json.JSONDecodeError:
            return html.Div("策略配置解析失败", className="text-danger")

        symbols = [s["value"] for s in _get_cached_symbols()][:3]
        if not symbols:
            return html.Div("无可用标的", className="text-warning")

        step1 = step1 or 5
        values1 = []
        v = min1 or 1
        mx1 = max1 or 100
        while v <= mx1:
            values1.append(round(v, 1))
            v += step1

        has_2d = bool(param2 and min2 is not None and max2 is not None)
        values2 = []
        if has_2d:
            step2 = step2 or 5
            v2 = min2 or 1
            mx2 = max2 or 100
            while v2 <= mx2:
                values2.append(round(v2, 1))
                v2 += step2
            if len(values1) > 15:
                values1 = values1[:15]
            if len(values2) > 15:
                values2 = values2[:15]

        results = []
        original_params = sc.get("params", {}).copy()

        for v1 in values1:
            if has_2d:
                row_result = []
                for v2 in values2:
                    sc["params"] = {**original_params, param1: v1, param2: v2}
                    paper = PaperEngine(initial_capital=1000000.0)
                    positions = PositionService()
                    all_bars = []
                    for sym in symbols:
                        df = _load_bars(sym, start_date, end_date)
                        if len(df) == 0:
                            continue
                        for row in df.iter_rows():
                            all_bars.append(Bar(
                                ticker=row[0], market=row[8] if len(row) > 8 else "a_share",
                                open=float(row[2]), high=float(row[3]), low=float(row[4]),
                                close=float(row[5]), volume=int(row[6] or 0),
                                amount=float(row[7] or 0), bar_time=0.0,
                            ))
                    if not all_bars:
                        row_result.append(None)
                        continue
                    bars_pl = pl.DataFrame([{
                        "ticker": b.ticker, "bar_time": float(b.bar_time),
                        "open": b.open, "high": b.high, "low": b.low,
                        "close": b.close, "volume": b.volume, "amount": b.amount,
                        "market": b.market,
                    } for b in all_bars])
                    strategy = create_strategy(sc)
                    engine = BacktestEngine(bars_df=bars_pl, paper_engine=paper, position_service=positions)
                    res = _run_async(engine.run(strategy))
                    nav = res["nav_history"]
                    row_result.append(sharpe_ratio(nav))
                results.append(row_result)
            else:
                sc["params"] = {**original_params, param1: v1}
                paper = PaperEngine(initial_capital=1000000.0)
                positions = PositionService()
                all_bars = []
                for sym in symbols:
                    df = _load_bars(sym, start_date, end_date)
                    if len(df) == 0:
                        continue
                    for row in df.iter_rows():
                        all_bars.append(Bar(
                            ticker=row[0], market=row[8] if len(row) > 8 else "a_share",
                            open=float(row[2]), high=float(row[3]), low=float(row[4]),
                            close=float(row[5]), volume=int(row[6] or 0),
                            amount=float(row[7] or 0), bar_time=0.0,
                        ))
                if not all_bars:
                    results.append(None)
                    continue
                bars_pl = pl.DataFrame([{
                    "ticker": b.ticker, "bar_time": float(b.bar_time),
                    "open": b.open, "high": b.high, "low": b.low,
                    "close": b.close, "volume": b.volume, "amount": b.amount,
                    "market": b.market,
                } for b in all_bars])
                strategy = create_strategy(sc)
                engine = BacktestEngine(bars_df=bars_pl, paper_engine=paper, position_service=positions)
                res = _run_async(engine.run(strategy))
                nav = res["nav_history"]
                results.append(sharpe_ratio(nav))

        import plotly.graph_objects as go

        if has_2d:
            z = [[r if r is not None else 0 for r in row] for row in results]
            param_labels = {"fast": "快线", "slow": "慢线", "signal": "信号线",
                            "period": "周期", "std": "标准差", "overbought": "超买", "oversold": "超卖"}
            p1_label = param_labels.get(param1, param1)
            p2_label = param_labels.get(param2, param2)

            best_idx = max(
                ((i, j) for i, row in enumerate(z) for j, v in enumerate(row)),
                key=lambda x: z[x[0]][x[1]],
            )
            fig = go.Figure()
            fig.add_trace(go.Heatmap(
                z=z, x=values2, y=values1,
                colorscale="RdYlGn", name="Sharpe",
                hovertemplate=f"{p1_label}: %{{y}}<br>{p2_label}: %{{x}}<br>Sharpe: %{{z:.2f}}",
            ))
            fig.add_trace(go.Scatter(
                x=[values2[best_idx[1]]], y=[values1[best_idx[0]]],
                mode="markers", marker=dict(color="blue", size=12, symbol="star"),
                name=f"最优 (Sharpe: {z[best_idx[0]][best_idx[1]]:.2f})",
            ))
            fig.update_layout(
                height=350, margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title=p2_label, yaxis_title=p1_label,
            )
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=values1, y=results, mode="lines+markers",
                line=dict(color="#0d6efd"), name="Sharpe",
            ))
            best_v = values1[results.index(max(r for r in results if r is not None))]
            best_s = max(r for r in results if r is not None)
            fig.add_trace(go.Scatter(
                x=[best_v], y=[best_s], mode="markers",
                marker=dict(color="green", size=12, symbol="star"),
                name=f"最优 ({best_v}: {best_s:.2f})",
            ))
            param_labels = {"fast": "快线", "slow": "慢线", "signal": "信号线",
                            "period": "周期", "std": "标准差", "overbought": "超买", "oversold": "超卖"}
            fig.update_layout(
                height=300, margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title=param_labels.get(param1, param1), yaxis_title="Sharpe",
            )

        return dcc.Graph(figure=fig, config={"displayModeBar": False})
