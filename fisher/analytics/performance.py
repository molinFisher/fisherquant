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
    if len(rets) < 2:
        return 0.0
    mean_ret = sum(rets) / len(rets)
    excess = mean_ret - risk_free_rate / 252
    variance = sum((r - mean_ret) ** 2 for r in rets) / len(rets)
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

    b = beta(nav, benchmark)
    mean_p = sum(rets_p[-n:]) / n
    mean_b = sum(rets_b[-n:]) / n
    rf_daily = risk_free_rate / 252
    return (mean_p - rf_daily - b * (mean_b - rf_daily)) * 252


def information_ratio(nav: list[float], benchmark: list[float]) -> float:
    rets_p = daily_returns(nav)
    rets_b = daily_returns(benchmark)
    n = min(len(rets_p), len(rets_b))
    if n < 2:
        return 0.0

    tracking_errors = [rets_p[i] - rets_b[i] for i in range(n)]
    mean_te = sum(tracking_errors) / n
    var_te = sum((te - mean_te) ** 2 for te in tracking_errors) / n
    if var_te == 0:
        return 0.0
    return (mean_te / math.sqrt(var_te)) * math.sqrt(252)


def turnover(trades: list[dict], nav_series: list[float]) -> float:
    if not trades or len(nav_series) < 2:
        return 0.0
    total_traded = sum(abs(t["price"] * t["quantity"]) for t in trades)
    avg_nav = sum(nav_series) / len(nav_series)
    if avg_nav == 0:
        return 0.0
    return total_traded / avg_nav


def compute_all_metrics(
    nav: list[float],
    benchmark_nav: list[float] | None = None,
    risk_free_rate: float = 0.02,
) -> dict[str, float]:
    if benchmark_nav is None:
        benchmark_nav = nav[:]

    return {
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
