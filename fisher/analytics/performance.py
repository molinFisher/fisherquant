import math
from .stats import compute_beta


def daily_returns(nav: list[float]) -> list[float]:
    if len(nav) < 2:
        return []
    return [(nav[i] - nav[i - 1]) / nav[i - 1] for i in range(1, len(nav))]


def cumulative_return(nav: list[float]) -> float:
    if len(nav) < 2:
        return 0.0
    return (nav[-1] - nav[0]) / nav[0]


def annualized_return(nav: list[float], trading_days: int = 252) -> float:
    if len(nav) < 2:
        return 0.0
    total = cumulative_return(nav) + 1.0
    periods = len(nav) - 1
    if periods <= 0:
        return 0.0
    return total ** (trading_days / periods) - 1.0


def sharpe_ratio(nav: list[float], risk_free_rate: float = 0.02) -> float:
    rets = daily_returns(nav)
    if len(rets) < 3:
        return 0.0
    mean_ret = sum(rets) / len(rets)
    excess = mean_ret - risk_free_rate / 252
    # P2-15：样本方差（n-1），避免系统性低估波动
    variance = sum((r - mean_ret) ** 2 for r in rets) / (len(rets) - 1)
    if variance == 0:
        return 0.0
    return (excess / math.sqrt(variance)) * math.sqrt(252)


def sortino_ratio(nav: list[float], risk_free_rate: float = 0.02) -> float:
    rets = daily_returns(nav)
    if len(rets) < 2:
        return 0.0
    mean_ret = sum(rets) / len(rets)
    excess = mean_ret - risk_free_rate / 252
    downside_only = [min(r - risk_free_rate / 252, 0) for r in rets if r < risk_free_rate / 252]
    if len(downside_only) == 0:
        return float("inf") if excess > 0 else 0.0
    downside_var = sum(d ** 2 for d in downside_only) / len(downside_only)
    if downside_var == 0:
        return float("inf") if excess > 0 else 0.0
    return (excess / math.sqrt(downside_var)) * math.sqrt(252)


def max_drawdown(nav: list[float]) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav[0]
    mdd = 0.0
    for n in nav:
        if n > peak:
            peak = n
        dd = (peak - n) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return mdd


def win_rate(nav: list[float]) -> float:
    rets = daily_returns(nav)
    if not rets:
        return 0.0
    wins = sum(1 for r in rets if r > 0)
    return wins / len(rets)


def profit_factor(trades: list[dict]) -> float:
    gross_profit = sum(t["profit"] for t in trades if t.get("profit", 0) > 0)
    gross_loss = abs(sum(t["profit"] for t in trades if t.get("profit", 0) < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def beta(nav: list[float], benchmark: list[float]) -> float:
    return compute_beta(daily_returns(nav), daily_returns(benchmark))


def alpha(nav: list[float], benchmark: list[float], risk_free_rate: float = 0.02) -> float:
    rets_p = daily_returns(nav)
    rets_b = daily_returns(benchmark)
    n = min(len(rets_p), len(rets_b))
    if n < 2:
        return 0.0

    # P2-15：beta / alpha / IR 统一使用相同的前 n 个对齐样本，口径一致
    nav_a = nav[: n + 1]
    bench_a = benchmark[: n + 1]
    b = beta(nav_a, bench_a)
    mean_p = sum(rets_p[:n]) / n
    mean_b = sum(rets_b[:n]) / n
    rf_daily = risk_free_rate / 252
    return (mean_p - rf_daily - b * (mean_b - rf_daily)) * 252


def information_ratio(nav: list[float], benchmark: list[float]) -> float:
    rets_p = daily_returns(nav)
    rets_b = daily_returns(benchmark)
    n = min(len(rets_p), len(rets_b))
    if n < 2:
        return 0.0

    # P2-15：与 alpha 一致，取前 n 个对齐样本
    tracking_errors = [rets_p[i] - rets_b[i] for i in range(n)]
    mean_te = sum(tracking_errors) / n
    var_te = sum((te - mean_te) ** 2 for te in tracking_errors) / n
    if var_te == 0:
        return 0.0
    return (mean_te / math.sqrt(var_te)) * math.sqrt(252)


def turnover(trades: list[dict], nav_series: list[float], position_values: list[float] | None = None) -> float:
    if not trades or len(nav_series) < 2:
        return 0.0
    total_traded = sum(abs(t["price"] * t["quantity"]) for t in trades)
    # P2-15：换手率分母用平均持仓市值（平均总持仓），而非平均净值
    if position_values is not None and len(position_values) >= 2:
        denom = sum(position_values) / len(position_values)
    else:
        denom = sum(nav_series) / len(nav_series)
    if denom == 0:
        return 0.0
    return total_traded / denom


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """标准正态分位数的 Acklam 近似（避免依赖 scipy），|误差| < 1.15e-9。"""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
         3.754408661907416]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
                 ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / \
        (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def probabilistic_sharpe_ratio(sharpe: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """概率夏普比率（PSR）：给定样本量下，真实 SR>0 的概率。"""
    if n_obs < 2:
        return 0.0
    denom = math.sqrt(1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe ** 2)
    if denom <= 0:
        return 0.0
    t = sharpe * math.sqrt(n_obs) / denom
    return _norm_cdf(t)


def deflated_sharpe_ratio(sharpe: float, n_obs: int, n_trials: int = 1,
                          skew: float = 0.0, kurt: float = 3.0) -> float:
    """Deflated Sharpe Ratio（多重比较校正）。

    在 PSR 基础上，用 z = Φ⁻¹(1 - 1/n_trials) 对 SR 做显著性门槛修正，
    n_trials 为测试过的策略/参数组合数，越大越严格，缓解过拟合误判。
    """
    if n_obs < 2 or n_trials < 1:
        return 0.0
    z = _norm_ppf(1.0 - 1.0 / n_trials) if n_trials > 1 else 0.0
    denom = math.sqrt(1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe ** 2)
    if denom <= 0:
        return 0.0
    t = (sharpe * math.sqrt(n_obs) - z) / denom
    return _norm_cdf(t)


def compute_all_metrics(
    nav: list[float],
    benchmark_nav: list[float] | None = None,
    risk_free_rate: float = 0.02,
    gross_nav: list[float] | None = None,
    n_trials: int = 1,
) -> dict[str, float]:
    if benchmark_nav is None:
        benchmark_nav = nav[:]

    metrics = {
        "cumulative_return": round(cumulative_return(nav), 6),
        "annualized_return": round(annualized_return(nav), 6),
        "sharpe_ratio": round(sharpe_ratio(nav, risk_free_rate), 4),
        "sortino_ratio": round(sortino_ratio(nav, risk_free_rate), 4),
        "max_drawdown": round(max_drawdown(nav), 4),
        "win_rate": round(win_rate(nav), 4),
        "beta": round(beta(nav, benchmark_nav), 4),
        "alpha": round(alpha(nav, benchmark_nav, risk_free_rate), 4),
        "information_ratio": round(information_ratio(nav, benchmark_nav), 4),
    }

    # P1-9 / P2-15：过拟合防护 + 成本拖累对比
    metrics["deflated_sharpe_ratio"] = round(
        deflated_sharpe_ratio(metrics["sharpe_ratio"], len(nav) - 1, n_trials=n_trials), 4
    )
    if gross_nav is not None and len(gross_nav) == len(nav) and len(nav) >= 2:
        net_ret = cumulative_return(nav)
        gross_ret = cumulative_return(gross_nav)
        metrics["gross_return"] = round(gross_ret, 6)
        metrics["fee_drag"] = round(gross_ret - net_ret, 6)

    return metrics
