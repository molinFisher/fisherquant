"""量化系统 16 项改进回归套件（P0-1~6, P1-8, P2-16）。

源自仓库根目录的 test_backtest_fixes.py，改写为 pytest 风格（check() -> assert），
纳入 tests/regression/ 以便 `pytest` 自动收集。覆盖回测/撮合/风险/条件单/做空/涨跌停封板。

运行：.venv/Scripts/python.exe -m pytest tests/regression/test_quant_fixes.py -v
"""
import asyncio
from datetime import datetime, timedelta

import polars as pl

from fisher.backtest.engine import BacktestEngine
from fisher.paper.engine import PaperEngine
from fisher.position.service import PositionService
from fisher.risk.engine import RiskEngine
from fisher.risk.pre_trade import MaxPositionRule
from fisher.event.types import Bar, Signal, OrderSide
from fisher.oms.orders import create_order, Order
from fisher.strategy.base import Strategy
from fisher.config.schemas import AssetFeeConfig


def make_bars(tickers, n_days, base_prices, drift=0.0, seed=0):
    rows = []
    start = datetime(2024, 1, 1)
    for d in range(n_days):
        dt = start + timedelta(days=d)
        ts = dt.timestamp()
        ds = dt.strftime("%Y-%m-%d")
        for t, base in zip(tickers, base_prices):
            price = base * (1 + drift * d)
            op = price * 0.99
            hi = price * 1.02
            lo = price * 0.98
            cl = price
            rows.append({
                "ticker": t, "trade_date": ds, "bar_time": ts,
                "open": round(op, 2), "high": round(hi, 2), "low": round(lo, 2),
                "close": round(cl, 2), "volume": 1_000_000, "amount": round(cl * 1_000_000, 2),
                "market": "a_share",
            })
    return pl.DataFrame(rows)


class ScriptStrategy(Strategy):
    name = "script"

    def __init__(self, params=None, script=None, allow_short=False):
        super().__init__(params)
        self._script = script or {}
        self._seen = {}
        self._allow_short = allow_short

    async def on_bar(self, bar):
        self._seen[bar.ticker] = self._seen.get(bar.ticker, 0) + 1
        idx = self._seen[bar.ticker]
        for a in self._script.get(bar.ticker, []):
            if a["at"] != idx:
                continue
            side = OrderSide.BUY if a["type"] == "buy" else OrderSide.SELL
            self.emit_signal(bar.ticker, bar.market, side, a["qty"], price=bar.close, confidence=1.0)


def run_engine(bars, script, slippage_bps=0.0, risk_engine=None, allow_short=False, seed=None, enable_risk=True):
    fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
    paper = PaperEngine(fee_config=fee, initial_capital=1_000_000.0,
                        slippage_bps=slippage_bps, allow_short=allow_short)
    pos = PositionService(allow_short=allow_short)
    eng = BacktestEngine(bars_df=bars, paper_engine=paper, position_service=pos,
                        risk_engine=risk_engine, seed=seed, enable_risk=enable_risk)
    strat = ScriptStrategy(script=script, allow_short=allow_short)
    res = asyncio.run(eng.run(strat))
    return res, paper, pos


# ---------------- P0-1 NAV 单一账本 ----------------
def test_nav_single_ledger():
    tickers = ["000001.SZ", "600519.SH"]
    bars = make_bars(tickers, 20, [10.0, 100.0], drift=0.001)
    script = {
        "000001.SZ": [{"at": 1, "type": "buy", "qty": 1000}],
        "600519.SH": [{"at": 1, "type": "buy", "qty": 500}],
    }
    res, paper, pos = run_engine(bars, script)
    nav = res["nav_history"][-1]
    avail = paper.get_account()["available"]
    pos_mv = sum(p["market_value"] for p in pos.get_all_positions().values())
    correct = abs(nav - (avail + pos_mv)) < 1.0
    # 旧 bug：nav == available + 2*pos_mv（重复记账）
    buggy = abs(nav - (avail + 2 * pos_mv)) < 1.0
    assert correct and not buggy, f"nav={nav:.2f} avail+posmv={avail+pos_mv:.2f}"


# ---------------- P0-2 无同根向前看 ----------------
def test_no_lookahead():
    tickers = ["000001.SZ"]
    bars = make_bars(tickers, 20, [10.0], drift=0.001)
    script = {"000001.SZ": [{"at": 1, "type": "buy", "qty": 1000}]}
    res, paper, pos = run_engine(bars, script)
    buy_trades = [t for t in res["trades"] if t["side"] == "buy"]
    detail = ""
    if buy_trades:
        first_date = bars.filter(pl.col("ticker") == "000001.SZ")["trade_date"][0]
        # 信号在首个 bar 生成，成交应延迟到下一根 bar（trade_date 不同且更晚）
        for t in buy_trades:
            if t["trade_date"] == first_date:
                detail = f"成交与信号同日 {t['trade_date']}"
                break
    assert not detail, detail or "ok"


# ---------------- P0-3 滑点 ----------------
def test_slippage():
    tickers = ["000001.SZ"]
    bars = make_bars(tickers, 20, [10.0], drift=0.0)
    script = {"000001.SZ": [{"at": 1, "type": "buy", "qty": 1000}]}
    res, paper, pos = run_engine(bars, script, slippage_bps=10.0)
    buy = [t for t in res["trades"] if t["side"] == "buy"]
    assert buy, "无成交"
    fill = buy[0]["price"]
    # 滑点后买入价应高于收盘价（10.0）
    expected = 10.0 * (1 + 10.0 / 10000.0)
    assert fill > 10.0 and abs(fill - expected) < 0.05, f"fill={fill:.4f} expected~{expected:.4f}"


# ---------------- P0-4 T+1（PositionService 单元） ----------------
def test_t1_unit():
    pos = PositionService()
    order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
    order.filled_qty = 100
    order.filled_price = 10.0
    order.commission = 0.0
    pos.update_on_fill(order, 10.0)
    avail_after_buy = pos.get_position("000001.SZ")["available"]
    pos.settle_t1()
    avail_after_settle = pos.get_position("000001.SZ")["available"]
    sell = create_order("000001.SZ", "a_share", "stock", OrderSide.SELL, 100, 10.0)
    sell.filled_qty = 100
    sell.filled_price = 10.0
    sell.commission = 0.0
    try:
        pos.update_on_fill(sell, 10.0)
        sold_ok = pos.get_position("000001.SZ") is None
    except Exception:
        sold_ok = False
    assert avail_after_buy == 0 and avail_after_settle == 100 and sold_ok, \
        f"buy_avail={avail_after_buy} settle_avail={avail_after_settle} sold={sold_ok}"


# ---------------- P0-5 风险引擎拒单 ----------------
def test_risk_reject():
    tickers = ["000001.SZ"]
    bars = make_bars(tickers, 20, [10.0], drift=0.001)
    script = {"000001.SZ": [{"at": 1, "type": "buy", "qty": 1000}]}
    risk = RiskEngine(rules=[MaxPositionRule(max_pct=0.0001)])  # 极小上限
    res, paper, pos = run_engine(bars, script, risk_engine=risk, enable_risk=True)
    rejected = len(res.get("risk_rejections", [])) > 0
    # 持仓市值应被上限约束（1000股*10≈10000 远超 1e6*0.0001=100）
    pos_val = sum(p["market_value"] for p in pos.get_all_positions().values())
    assert rejected and pos_val <= 100.0 + 1.0, \
        f"rejections={len(res.get('risk_rejections',[]))} pos_val={pos_val:.2f}"


# ---------------- P0-6 条件单触发 ----------------
def test_conditions():
    fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
    paper = PaperEngine(fee_config=fee, initial_capital=1_000_000.0,
                        slippage_bps=0.0, allow_short=False)
    # 先买入建仓
    buy = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 1000, 10.0)
    paper.submit_order(buy)
    bars = make_bars(["000001.SZ"], 10, [10.0], drift=0.0)
    # 跑若干根让买入成交
    for b in bars.iter_rows(named=True):
        bar = Bar(ticker=b["ticker"], market="a_share", open=b["open"], high=b["high"],
                  low=b["low"], close=b["close"], volume=b["volume"], amount=b["amount"],
                  bar_time=b["bar_time"])
        paper.on_bar(bar)
    # 挂止损（市价 <= 9.5 触发）
    stop = create_order("000001.SZ", "a_share", "stock", OrderSide.SELL, 1000, 9.5,
                        condition_price=9.5, condition_type="stop_loss")
    paper.submit_order(stop)
    # 推动价格跌破 9.5
    drop_bars = []
    start = datetime(2024, 1, 1)
    for d in range(3):
        dt = start + timedelta(days=20 + d)
        ts = dt.timestamp()
        drop_bars.append(Bar(ticker="000001.SZ", market="a_share", open=9.6, high=9.7,
                             low=9.3, close=9.3, volume=1_000_000, amount=9.3e6, bar_time=ts))
    for bar in drop_bars:
        paper.check_conditions("000001.SZ", bar.close)
        paper.on_bar(bar)
    pos = paper.get_positions().get("000001.SZ")
    sold = pos is None or pos["quantity"] == 0
    assert sold, f"pos={paper.get_positions().get('000001.SZ')}"


# ---------------- P1-8 做空 ----------------
def test_short():
    tickers = ["000001.SZ"]
    bars = make_bars(tickers, 20, [10.0], drift=0.001)
    # 无持仓直接卖出（做空）
    script = {"000001.SZ": [{"at": 1, "type": "sell", "qty": 500}]}
    res, paper, pos = run_engine(bars, script, allow_short=True)
    p = pos.get_position("000001.SZ")
    short_ok = p is not None and p["quantity"] == -500
    nav = res["nav_history"][-1]
    # 做空后现金应增加（卖出获得资金），净值 = 现金 + 负市值
    avail = paper.get_account()["available"]
    assert short_ok and avail > 1_000_000.0, \
        f"qty={p['quantity'] if p else None} avail={avail:.2f}"


# ---------------- P2-16 涨跌停不可成交 ----------------
def test_limit_lock():
    fee = AssetFeeConfig(commission_rate=0.00025, min_commission=5.0)
    paper = PaperEngine(fee_config=fee, initial_capital=1_000_000.0, slippage_bps=0.0)
    buy = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 1000, 11.0)
    paper.submit_order(buy)
    # 第一根：正常 bar，建立前收盘价 10.0（订单延迟到下一根撮合）
    bar1 = Bar(ticker="000001.SZ", market="a_share", open=10.0, high=10.2, low=9.9,
               close=10.0, volume=1_000_000, amount=10.0e6, bar_time=1.0)
    filled1 = paper.on_bar(bar1)
    # 第二根：涨停封死（close == high == 前收*1.10）→ 买单无法成交
    bar2 = Bar(ticker="000001.SZ", market="a_share", open=10.5, high=11.0, low=10.4,
               close=11.0, volume=1_000_000, amount=11.0e6, bar_time=2.0)
    filled2 = paper.on_bar(bar2)
    # 第三根：继续一字涨停封死（前收 11.0 → 12.1）→ 依然无法成交
    bar3 = Bar(ticker="000001.SZ", market="a_share", open=12.1, high=12.1, low=12.1,
               close=12.1, volume=1_000_000, amount=12.1e6, bar_time=3.0)
    filled3 = paper.on_bar(bar3)
    assert len(filled1) == 0 and len(filled2) == 0 and len(filled3) == 0, \
        f"filled={len(filled1)+len(filled2)+len(filled3)}"
