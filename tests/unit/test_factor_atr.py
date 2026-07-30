import polars as pl
import numpy as np
import pandas as pd

from fisher.factor import register_all_factors
from fisher.factor.registry import FactorRegistry
from fisher.factor.volatility import Atr
from fisher.factor.technical import MACD, RSI14, BollingerBands
from fisher.factor.price import (
    Momentum20D,
    Momentum60D,
    Volatility20D,
    Volatility60D,
    Turnover5D,
    Turnover20D,
    VolumeRatio,
)

# 已实现因子类（直接遍历，避免受其他测试向全局注册表注入的因子干扰）
_KNOWN_FACTOR_INSTANCES = [
    MACD(), RSI14(), BollingerBands(),
    Momentum20D(), Momentum60D(),
    Volatility20D(), Volatility60D(),
    Turnover5D(), Turnover20D(),
    VolumeRatio(), Atr(),
]


# ---------------------------------------------------------------------------
# TC-1 注册自检：register_all_factors 后注册表含全部已实现因子（≥11，含 atr）
# ---------------------------------------------------------------------------
def test_register_all_factors_registers_atr_and_others():
    register_all_factors()
    names = {f.name for f in FactorRegistry.list_all()}
    expected = {
        "macd", "rsi_14", "bollinger",
        "momentum_20d", "momentum_60d",
        "volatility_20d", "volatility_60d",
        "turnover_5d", "turnover_20d", "volume_ratio",
        "atr",
    }
    for e in expected:
        assert e in names, f"因子未注册: {e}"
    assert len(names) >= 11


# ---------------------------------------------------------------------------
# TC-2 各已注册因子冒烟：样例 OHLC 上 compute 不抛错且产出 output_columns
# ---------------------------------------------------------------------------
def test_all_registered_factors_smoke():
    base = pl.DataFrame({
        "open": [10.0, 10.5, 11.0, 10.8, 11.2, 11.0, 11.5],
        "high": [10.6, 11.1, 11.4, 11.0, 11.6, 11.3, 11.8],
        "low": [9.8, 10.2, 10.7, 10.5, 11.0, 10.7, 11.1],
        "close": [10.2, 10.8, 11.2, 10.7, 11.3, 11.1, 11.6],
        "volume": [1000, 1100, 1200, 900, 1300, 800, 1400],
    })
    for f in _KNOWN_FACTOR_INSTANCES:
        out = f.compute(base.clone())
        for c in f.output_columns:
            assert c in out.columns, f"{f.name} 缺少输出列 {c}"


# ---------------------------------------------------------------------------
# TC-3 ATR 公式：tr == max(H-L, |H-preC|, |L-preC|)
# ---------------------------------------------------------------------------
def test_atr_tr_formula():
    df = pl.DataFrame({
        "open": [10.0, 10.5, 11.0, 10.8, 11.2],
        "high": [10.5, 11.0, 11.4, 11.0, 11.6],
        "low": [9.8, 10.2, 10.7, 10.5, 11.0],
        "close": [10.2, 10.8, 11.2, 10.7, 11.3],
    })
    out = Atr().compute(df)
    tr = out["tr"].to_list()
    high = [10.5, 11.0, 11.4, 11.0, 11.6]
    low = [9.8, 10.2, 10.7, 10.5, 11.0]
    close = [10.2, 10.8, 11.2, 10.7, 11.3]
    for i in range(len(df)):
        pc = close[i - 1] if i > 0 else close[i]  # 首行 prev_close 视作自身 → tr=h-l
        expected = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))
        assert abs(tr[i] - expected) < 1e-9, f"tr[{i}]={tr[i]} != {expected}"


# ---------------------------------------------------------------------------
# TC-4 ATR 滚动均值：与 pandas 参照 rolling(period).mean() 在 ±1e-6 内一致
# ---------------------------------------------------------------------------
def test_atr_rolling_mean_matches_pandas():
    period = 14
    n = 60
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    df = pl.DataFrame({
        "open": close + rng.normal(0, 0.2, n),
        "high": high,
        "low": low,
        "close": close,
    })
    out = Atr().compute(df)
    atr = out["atr"].to_list()

    # pandas 参照
    pdf = pd.DataFrame({"high": high, "low": low, "close": close})
    prev_close = pdf["close"].shift(1)
    tr = pd.concat(
        [
            (pdf["high"] - pdf["low"]).abs(),
            (pdf["high"] - prev_close).abs(),
            (pdf["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    exp_atr = tr.rolling(period).mean().to_list()

    for i in range(period - 1, n):
        assert abs(atr[i] - exp_atr[i]) < 1e-6, f"atr[{i}]={atr[i]} != {exp_atr[i]}"


# ---------------------------------------------------------------------------
# TC-5 边界：前 period-1 行 atr/tr 为 null
# ---------------------------------------------------------------------------
def test_atr_leading_nulls():
    period = 14
    n = 20
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pl.DataFrame({
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
    })
    a = Atr()
    a.default_period = period
    out = a.compute(df)
    atr = out["atr"].to_list()
    for i in range(period - 1):
        assert atr[i] is None, f"atr[{i}] 应为 null（前 period-1 行）"
    assert atr[period - 1] is not None


# ---------------------------------------------------------------------------
# TC-6 除权日连续性：有前复权因子的 ATR 不应出现除权缺口导致的异常跳变
# ---------------------------------------------------------------------------
def test_atr_adj_continuity_on_dividend_gap():
    # 日4 发生约 23% 的除权下跌（raw），但 adj_factor 使其前复权后连续
    raw_close = [100.0, 101.0, 102.0, 103.0, 80.0, 81.0, 82.0, 83.0]
    adj_close = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]  # 平滑目标
    adj_factor = [raw_close[i] / adj_close[i] for i in range(8)]
    df_adj = pl.DataFrame({
        "open": raw_close,
        "high": [c + 1 for c in raw_close],
        "low": [c - 1 for c in raw_close],
        "close": raw_close,
        "adj_factor": adj_factor,
    })
    df_raw = df_adj.drop("adj_factor")

    a = Atr()
    a.default_period = 3  # 小窗口放大对比
    atr_adj = a.compute(df_adj)["atr"].to_list()
    atr_raw = a.compute(df_raw)["atr"].to_list()

    # 前复权后 ATR 明显小于不复权（除权缺口不再造成虚假放大）
    max_adj = max(v for v in atr_adj if v is not None)
    max_raw = max(v for v in atr_raw if v is not None)
    assert max_adj < max_raw * 0.5


# ---------------------------------------------------------------------------
# TC-7 缺复权降级：无 adj_factor 列 / 全 null 时不抛错，退化为不复权
# ---------------------------------------------------------------------------
def test_atr_fallback_without_adj_factor():
    a = Atr()
    a.default_period = 3  # 小样本，保证有非空输出
    df_no_col = pl.DataFrame({
        "open": [10.0, 10.5, 11.0],
        "high": [10.6, 11.1, 11.4],
        "low": [9.8, 10.2, 10.7],
        "close": [10.2, 10.8, 11.2],
    })
    out = a.compute(df_no_col)
    assert "atr" in out.columns and "tr" in out.columns
    assert out["atr"][-1] is not None

    df_null_adj = df_no_col.with_columns(pl.Series("adj_factor", [None, None, None]))
    out2 = a.compute(df_null_adj)
    assert out2["atr"][-1] is not None


# ---------------------------------------------------------------------------
# TC-8 UI 状态映射：atr 标"可用"，sma_5 等未实现项标"未实现"（FR-4）
# ---------------------------------------------------------------------------
def test_ui_factor_status_mapping():
    from fisher.dash_app.pages.factor_center import _registered_names, FACTOR_DEFINITIONS

    reg = _registered_names()
    assert "atr" in reg, "atr 应已实现"
    assert "sma_5" not in reg, "sma_5 本期未实现"

    def_names = {f["name"] for f in FACTOR_DEFINITIONS}
    assert "atr" in def_names
    assert "sma_5" in def_names
    # 目录中存在未实现项（用于灰显），且至少 atr 已实现
    assert any(f["name"] not in reg for f in FACTOR_DEFINITIONS)
