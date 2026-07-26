"""其余改进模块冒烟验证：P1-9/P1-11/P2-14/P2-15/风险工厂/实盘占位。"""
import numpy as np

ok = []

# P1-11 组合方法
from fisher.portfolio.methods import risk_parity, kelly
merged = {
    "A": {"vol": 0.10, "confidence": 0.6},
    "B": {"vol": 0.20, "confidence": 0.6},
}
w = risk_parity(merged, 1_000_000)
# 低波动的 A 应获得更高权重
ok.append(("P1-11 risk_parity 逆波动率", w["A"] > w["B"] and abs(sum(w.values()) - 1) < 1e-6, w))

cov = {"A": {"B": 0.002}, "B": {"A": 0.002}}
w2 = risk_parity(merged, 1_000_000, cov=cov)
ok.append(("P1-11 risk_parity ERC(协方差)", w2["A"] > w2["B"] and abs(sum(w2.values()) - 1) < 1e-6, w2))

kw = kelly({"A": {"confidence": 0.9, "win_loss_ratio": 5.0}, "B": {"confidence": 0.55, "win_loss_ratio": 1.2}})
# 单标的上限 = max_per_asset(0.25) * fraction(0.5) = 0.125；总仓位不加杠杆
ok.append(("P1-11 kelly 分数凯利不爆仓",
           all(0 <= v <= 0.125 + 1e-9 for v in kw.values()) and sum(kw.values()) <= 1.0 + 1e-9, kw))

# P2-15 绩效指标
from fisher.analytics.performance import (
    sharpe_ratio, probabilistic_sharpe_ratio, deflated_sharpe_ratio, compute_all_metrics,
)
rng = np.random.default_rng(42)
rets = rng.normal(0.001, 0.01, 252).tolist()
sr = sharpe_ratio(rets)
sr_per_bar = sr / np.sqrt(252)  # PSR/DSR 用未年化的 per-bar SR
psr = probabilistic_sharpe_ratio(sr_per_bar, len(rets))
dsr = deflated_sharpe_ratio(sr_per_bar, len(rets), n_trials=10)
ok.append(("P2-15 sharpe(n-1)/PSR/DSR", isinstance(sr, float) and 0 <= psr <= 1 and 0 <= dsr <= 1,
           f"sr={sr:.3f} psr={psr:.3f} dsr={dsr:.3f}"))

nav = list(np.cumprod([1 + r for r in rets]) * 1e6)
gross = [v * 1.001 for v in nav]
m = compute_all_metrics(nav, gross_nav=gross, n_trials=5)
ok.append(("P2-15 compute_all_metrics 扩展字段",
           "deflated_sharpe_ratio" in m and "fee_drag" in m and "gross_return" in m,
           {k: m[k] for k in ("deflated_sharpe_ratio", "fee_drag") if k in m}))

# P1-9 walk-forward
from fisher.strategy.walk_forward import train_test_split, walk_forward
import polars as pl
from datetime import datetime, timedelta
rows = []
for d in range(120):
    dt = datetime(2024, 1, 1) + timedelta(days=d)
    rows.append({"ticker": "T", "trade_date": dt.strftime("%Y-%m-%d"), "bar_time": dt.timestamp(),
                 "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0 + 0.01 * d,
                 "volume": 1e6, "amount": 1e7, "market": "a_share"})
df = pl.DataFrame(rows)
tr, te = train_test_split(df, train_frac=0.7)
ok.append(("P1-9 train_test_split", len(tr) > len(te) and len(tr) + len(te) == len(df), f"{len(tr)}/{len(te)}"))

def dummy_run(test_df):
    closes = test_df["close"].to_list()
    nav = [1_000_000.0]
    for i in range(1, len(closes)):
        nav.append(nav[-1] * (closes[i] / closes[i - 1]))
    return {"nav_history": nav}

wf = walk_forward(df, dummy_run, n_splits=3, train_size=0.6)
ok.append(("P1-9 walk_forward 滚动样本外", wf.get("ok") and wf["n_folds"] == 3 and "stable" in wf,
           f"folds={wf.get('n_folds')} dsr={wf.get('deflated_sharpe_ratio')} stable={wf.get('stable')}"))

# P2-14 可复现
from fisher.backtest.repro import set_global_seed, compute_input_hash, bars_fingerprint
set_global_seed(123)
a = np.random.rand(5)
set_global_seed(123)
b = np.random.rand(5)
fp = bars_fingerprint(df)
h1 = compute_input_hash(fp, {"name": "strategy_a"}, {"x": 1})
h2 = compute_input_hash(fp, {"name": "strategy_a"}, {"x": 1})
ok.append(("P2-14 种子/输入指纹", np.allclose(a, b) and h1 == h2 and len(fp) > 0, f"hash={h1[:12]}"))

# P0-5 风险工厂（用真实 configs/risk.yaml 验证）
from fisher.risk.factory import build_risk_engine, load_risk_config
import os
cfg = load_risk_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "risk.yaml"))
eng = build_risk_engine(cfg)
n_rules = len(eng._rules) if eng is not None else 0
ok.append(("P0-5 风险工厂 risk.yaml→RiskEngine", eng is not None and n_rules >= 3, f"rules={n_rules}"))

# P2-13 实盘占位
from fisher.broker.live import LiveBrokerAdapter
try:
    LiveBrokerAdapter()  # 无凭证应显式拒绝
    live_ok = False
    detail = "未拦截缺失凭证"
except ValueError as e:
    live_ok = True
    detail = "缺失凭证被显式拒绝"
ok.append(("P2-13 实盘适配器占位", live_ok, detail))

passed = 0
for name, cond, detail in ok:
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    passed += cond
print(f"\n==== {passed}/{len(ok)} 通过 ====")
import sys
sys.exit(0 if passed == len(ok) else 1)
