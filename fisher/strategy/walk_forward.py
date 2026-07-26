"""过拟合防护（对应 P1-9）。

提供：
- train_test_split：单次样本内/样本外切分；
- walk_forward：滚动窗口样本外评估，给出各 fold 指标与多重比较校正后的
  Deflated Sharpe Ratio，用于判断策略是否过拟合。
"""
import polars as pl
from ..analytics.performance import compute_all_metrics, deflated_sharpe_ratio


def _unique_dates(bars_df: pl.DataFrame) -> list:
    return bars_df.select("trade_date").unique().sort("trade_date")["trade_date"].to_list()


def train_test_split(bars_df: pl.DataFrame, train_frac: float = 0.6):
    """按时间切分为样本内 / 样本外两段。"""
    dates = _unique_dates(bars_df)
    n = len(dates)
    if n < 4:
        return bars_df, bars_df
    cut = max(1, int(n * train_frac))
    train_dates = dates[:cut]
    test_dates = dates[cut:]
    train_df = bars_df.filter(pl.col("trade_date").is_in(train_dates))
    test_df = bars_df.filter(pl.col("trade_date").is_in(test_dates))
    return train_df, test_df


def walk_forward(bars_df: pl.DataFrame, run_fn, n_splits: int = 5, train_size: float = 0.6) -> dict:
    """滚动窗口样本外评估。

    run_fn(test_df) -> {"nav_history": [...], ...}，对每个测试窗口独立回测。
    返回各 fold 的累计收益 / 夏普，以及多重比较校正后的 Deflated Sharpe。
    """
    dates = _unique_dates(bars_df)
    n = len(dates)
    if n < 2 * n_splits or n_splits < 1:
        return {"ok": False, "reason": "数据不足以做 walk-forward", "folds": []}

    fold_len = max(1, n // (n_splits + 1))
    folds = []
    for i in range(n_splits):
        s = i * fold_len
        e = min(s + fold_len, n)
        if e <= s:
            continue
        test_dates = dates[s:e]
        test_df = bars_df.filter(pl.col("trade_date").is_in(test_dates))
        if test_df.height == 0:
            continue
        result = run_fn(test_df)
        nav = result.get("nav_history")
        if not nav or len(nav) < 3:
            continue
        m = compute_all_metrics(nav)
        folds.append({
            "start": test_dates[0],
            "end": test_dates[-1],
            "cumulative_return": m["cumulative_return"],
            "sharpe_ratio": m["sharpe_ratio"],
            "max_drawdown": m["max_drawdown"],
        })

    if not folds:
        return {"ok": False, "reason": "无有效 fold", "folds": []}

    sharpes = [f["sharpe_ratio"] for f in folds]
    avg_sharpe = sum(sharpes) / len(sharpes)
    # n_trials 取 fold 数（每次评估等同一次独立试验），做多重比较校正
    dsr = deflated_sharpe_ratio(avg_sharpe, len(dates) - 1, n_trials=len(folds))
    returns = [f["cumulative_return"] for f in folds]
    return {
        "ok": True,
        "n_folds": len(folds),
        "avg_sharpe": round(avg_sharpe, 4),
        "avg_return": round(sum(returns) / len(returns), 6),
        "min_return": round(min(returns), 6),
        "max_return": round(max(returns), 6),
        "deflated_sharpe_ratio": round(dsr, 4),
        "stable": dsr > 0.9,  # DSR>0.9 视为统计上可信（非运气）
        "folds": folds,
    }
