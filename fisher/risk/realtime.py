import math
from collections import deque
from ..analytics.stats import compute_beta as _compute_beta


class RealtimeRiskMonitor:
    def __init__(
        self,
        var_confidence: float = 0.99,
        max_drawdown: float = 0.15,
        beta_limit: float = 1.5,
        lookback: int = 252,
    ):
        self._var_confidence = var_confidence
        self._max_drawdown = max_drawdown
        self._beta_limit = beta_limit
        self._returns: deque[float] = deque(maxlen=lookback)
        self._benchmark_returns: deque[float] = deque(maxlen=lookback)
        self._peak_nav: float = 0.0

    def add_return(self, portfolio_return: float, benchmark_return: float = 0.0) -> None:
        self._returns.append(portfolio_return)
        self._benchmark_returns.append(benchmark_return)

    def _as_list(self, dq: deque[float]) -> list[float]:
        return list(dq)

    def var(self) -> float:
        returns = self._as_list(self._returns)
        if len(returns) < 2:
            return 0.0
        sorted_returns = sorted(returns)
        idx = int(len(sorted_returns) * (1 - self._var_confidence))
        idx = max(0, min(idx, len(sorted_returns) - 1))
        return abs(sorted_returns[idx])

    def beta(self) -> float:
        returns = self._as_list(self._returns)
        bench = self._as_list(self._benchmark_returns)
        return _compute_beta(returns, bench)

    def max_drawdown(self, nav_series: list[float]) -> float:
        if not nav_series:
            return 0.0
        peak = nav_series[0]
        mdd = 0.0
        for nav in nav_series:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak if peak > 0 else 0.0
            if dd > mdd:
                mdd = dd
        return mdd

    def _peak_nav_from_series(self, nav_series: list[float]) -> float:
        return max(nav_series) if nav_series else 0.0

    def check_drawdown(self, current_nav: float) -> tuple[bool, str]:
        if current_nav > self._peak_nav:
            self._peak_nav = current_nav
            return True, ""

        dd = (self._peak_nav - current_nav) / self._peak_nav if self._peak_nav > 0 else 0.0
        if dd >= self._max_drawdown:
            return False, f"Drawdown {dd:.2%} >= {self._max_drawdown:.2%}"
        return True, ""

    def check_beta(self, current_beta: float) -> tuple[bool, str]:
        if abs(current_beta) > self._beta_limit:
            return False, f"Beta {current_beta:.2f} > limit {self._beta_limit:.2f}"
        return True, ""
