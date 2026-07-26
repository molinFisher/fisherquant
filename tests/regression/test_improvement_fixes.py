"""其余改进模块回归套件（P1-9/11, P2-13/14/15, P0-5 风险工厂）。

源自仓库根目录的 test_improvement_smoke.py，改写为 pytest 风格（ok.append -> assert），
纳入 tests/regression/ 以便 `pytest` 自动收集。

运行：.venv/Scripts/python.exe -m pytest tests/regression/test_improvement_fixes.py -v
"""
import os
from pathlib import Path

import numpy as np
import polars as pl
from datetime import datetime, timedelta


# ---------------- P1-11 组合方法 ----------------
def test_risk_parity_inverse_vol():
    from fisher.portfolio.methods import risk_parity
    merged = {
        "A": {"vol": 0.10, "confidence": 0.6},
        "B": {"vol": 0.20, "confidence": 0.6},
    }
    w = risk_parity(merged, 1_000_000)
    # 低波动的 A 应获得更高权重
    assert w["A"] > w["B"] and abs(sum(w.values()) - 1) < 1e-6, w


def test_risk_parity_erc_with_cov():
    from fisher.portfolio.methods import risk_parity
    merged = {
        "A": {"vol": 0.10, "confidence": 0.6},
        "B": {"vol": 0.20, "confidence": 0.6},
    }
    cov = {"A": {"B": 0.002}, "B": {"A": 0.002}}
    w2 = risk_parity(merged, 1_000_000, cov=cov)
    assert w2["A"] > w2["B"] and abs(sum(w2.values()) - 1) < 1e-6, w2


def test_kelly_no_blowup():
    from fisher.portfolio.methods import kelly
    kw = kelly({"A": {"confidence": 0.9, "win_loss_ratio": 5.0}, "B": {"confidence": 0.55, "win_loss_ratio": 1.2}})
    # 单标的上限 = max_per_asset(0.25) * fraction(0.5) = 0.125；总仓位不加杠杆
    assert all(0 <= v <= 0.125 + 1e-9 for v in kw.values()) and sum(kw.values()) <= 1.0 + 1e-9, kw


# ---------------- P2-15 绩效指标 ----------------
def test_sharpe_psr_dsr():
    from fisher.analytics.performance import (
        sharpe_ratio, probabilistic_sharpe_ratio, deflated_sharpe_ratio,
    )
    rng = np.random.default_rng(42)
    rets = rng.normal(0.001, 0.01, 252).tolist()
    sr = sharpe_ratio(rets)
    sr_per_bar = sr / np.sqrt(252)  # PSR/DSR 用未年化的 per-bar SR
    psr = probabilistic_sharpe_ratio(sr_per_bar, len(rets))
    dsr = deflated_sharpe_ratio(sr_per_bar, len(rets), n_trials=10)
    assert isinstance(sr, float) and 0 <= psr <= 1 and 0 <= dsr <= 1, \
        f"sr={sr:.3f} psr={psr:.3f} dsr={dsr:.3f}"


def test_compute_all_metrics_fields():
    from fisher.analytics.performance import compute_all_metrics
    rng = np.random.default_rng(42)
    rets = rng.normal(0.001, 0.01, 252).tolist()
    nav = list(np.cumprod([1 + r for r in rets]) * 1e6)
    gross = [v * 1.001 for v in nav]
    m = compute_all_metrics(nav, gross_nav=gross, n_trials=5)
    assert "deflated_sharpe_ratio" in m and "fee_drag" in m and "gross_return" in m, \
        {k: m[k] for k in ("deflated_sharpe_ratio", "fee_drag") if k in m}


# ---------------- P1-9 walk-forward ----------------
def test_train_test_split():
    from fisher.strategy.walk_forward import train_test_split
    rows = []
    for d in range(120):
        dt = datetime(2024, 1, 1) + timedelta(days=d)
        rows.append({"ticker": "T", "trade_date": dt.strftime("%Y-%m-%d"), "bar_time": dt.timestamp(),
                     "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0 + 0.01 * d,
                     "volume": 1e6, "amount": 1e7, "market": "a_share"})
    df = pl.DataFrame(rows)
    tr, te = train_test_split(df, train_frac=0.7)
    assert len(tr) > len(te) and len(tr) + len(te) == len(df), f"{len(tr)}/{len(te)}"


def test_walk_forward():
    from fisher.strategy.walk_forward import walk_forward

    def dummy_run(test_df):
        closes = test_df["close"].to_list()
        nav = [1_000_000.0]
        for i in range(1, len(closes)):
            nav.append(nav[-1] * (closes[i] / closes[i - 1]))
        return {"nav_history": nav}

    rows = []
    for d in range(120):
        dt = datetime(2024, 1, 1) + timedelta(days=d)
        rows.append({"ticker": "T", "trade_date": dt.strftime("%Y-%m-%d"), "bar_time": dt.timestamp(),
                     "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0 + 0.01 * d,
                     "volume": 1e6, "amount": 1e7, "market": "a_share"})
    df = pl.DataFrame(rows)
    wf = walk_forward(df, dummy_run, n_splits=3, train_size=0.6)
    assert wf.get("ok") and wf["n_folds"] == 3 and "stable" in wf, \
        f"folds={wf.get('n_folds')} dsr={wf.get('deflated_sharpe_ratio')} stable={wf.get('stable')}"


# ---------------- P2-14 可复现 ----------------
def test_seed_and_input_hash():
    from fisher.backtest.repro import set_global_seed, compute_input_hash, bars_fingerprint
    rows = []
    for d in range(120):
        dt = datetime(2024, 1, 1) + timedelta(days=d)
        rows.append({"ticker": "T", "trade_date": dt.strftime("%Y-%m-%d"), "bar_time": dt.timestamp(),
                     "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0 + 0.01 * d,
                     "volume": 1e6, "amount": 1e7, "market": "a_share"})
    df = pl.DataFrame(rows)
    set_global_seed(123)
    a = np.random.rand(5)
    set_global_seed(123)
    b = np.random.rand(5)
    fp = bars_fingerprint(df)
    h1 = compute_input_hash(fp, {"name": "strategy_a"}, {"x": 1})
    h2 = compute_input_hash(fp, {"name": "strategy_a"}, {"x": 1})
    assert np.allclose(a, b) and h1 == h2 and len(fp) > 0, f"hash={h1[:12]}"


# ---------------- P0-5 风险工厂（用真实 configs/risk.yaml 验证） ----------------
def test_risk_factory_from_yaml():
    from fisher.risk.factory import build_risk_engine, load_risk_config
    root = Path(__file__).resolve().parents[2]
    cfg = load_risk_config(str(root / "configs" / "risk.yaml"))
    eng = build_risk_engine(cfg)
    n_rules = len(eng._rules) if eng is not None else 0
    assert eng is not None and n_rules >= 3, f"rules={n_rules}"


# ---------------- P2-13 实盘占位 ----------------
def test_live_adapter_placeholder():
    from fisher.broker.live import LiveBrokerAdapter
    try:
        LiveBrokerAdapter()  # 无凭证应显式拒绝
        raise AssertionError("未拦截缺失凭证")
    except ValueError:
        pass  # 缺失凭证被显式拒绝
