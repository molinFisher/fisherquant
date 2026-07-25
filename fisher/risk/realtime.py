import math


class RealtimeRiskMonitor:
    def __init__(
        self,
        var_confidence: float = 0.99,
        max_drawdown: float = 0.15,
        beta_limit: float = 1.5,
    ):
        self._var_confidence = var_confidence
        self._max_drawdown = max_drawdown
        self._beta_limit = beta_limit
        self._returns: list[float] = []
        self._benchmark_returns: list[float] = []
        self._peak_nav: float = 0.0

    def add_return(self, portfolio_return: float, benchmark_return: float = 0.0) -> None:
        self._returns.append(portfolio_return)
        self._benchmark_returns.append(benchmark_return)

    def var(self) -> float:
        if len(self._returns) < 2:
            return 0.0
        sorted_returns = sorted(self._returns)
        idx = int(len(sorted_returns) * (1 - self._var_confidence))
        idx = max(0, min(idx, len(sorted_returns) - 1))
        return abs(sorted_returns[idx])

    def beta(self) -> float:
        if len(self._returns) < 2:
            return 0.0
        n = min(len(self._returns), len(self._benchmark_returns))
        portfolio = self._returns[-n:]
        benchmark = self._benchmark_returns[-n:]

        mean_p = sum(portfolio) / n
        mean_b = sum(benchmark) / n

        cov = sum((portfolio[i] - mean_p) * (benchmark[i] - mean_b) for i in range(n)) / n
        var_b = sum((b - mean_b) ** 2 for b in benchmark) / n

        if var_b == 0:
            return 0.0
        return cov / var_b

    def max_drawdown(self, nav_series: list[float]) -> float:
        peak = nav_series[0] if nav_series else 0.0
        mdd = 0.0
        for nav in nav_series:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak if peak > 0 else 0.0
            if dd > mdd:
                mdd = dd
        return mdd

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
