import pytest
import math
from fisher.analytics.performance import (
    daily_returns,
    cumulative_return,
    annualized_return,
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    win_rate,
    beta,
    alpha,
    information_ratio,
    compute_all_metrics,
)


class TestDailyReturns:
    def test_simple(self):
        nav = [100, 110, 121]
        returns = daily_returns(nav)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.10)
        assert returns[1] == pytest.approx(0.10)

    def test_single_point(self):
        assert daily_returns([100]) == []


class TestCumulativeReturn:
    def test_simple(self):
        assert cumulative_return([100, 110, 120]) == pytest.approx(0.20)

    def test_loss(self):
        assert cumulative_return([100, 90]) == pytest.approx(-0.10)


class TestAnnualizedReturn:
    def test_positive(self):
        nav = [100, 110, 121, 133.1, 146.41]
        ann_ret = annualized_return(nav, trading_days=252)
        assert ann_ret > 0

    def test_single_point(self):
        assert annualized_return([100], trading_days=252) == 0.0


class TestSharpeRatio:
    def test_positive(self):
        nav = [100, 101, 102, 103, 104]
        sr = sharpe_ratio(nav, risk_free_rate=0.02)
        assert sr > 0

    def test_insufficient_data(self):
        assert sharpe_ratio([100], risk_free_rate=0.02) == 0.0


class TestSortinoRatio:
    def test_positive(self):
        nav = [100, 101, 102, 103, 104]
        sr = sortino_ratio(nav, risk_free_rate=0.02)
        assert sr > 0

    def test_insufficient_data(self):
        assert sortino_ratio([100]) == 0.0


class TestMaxDrawdown:
    def test_standard(self):
        nav = [100, 110, 90, 95, 105]
        mdd = max_drawdown(nav)
        assert mdd > 0
        assert mdd == pytest.approx((110 - 90) / 110, rel=1e-4)

    def test_no_drawdown(self):
        nav = [100, 110, 120]
        assert max_drawdown(nav) == 0.0

    def test_single_point(self):
        assert max_drawdown([100]) == 0.0


class TestWinRate:
    def test_mixed(self):
        nav = [100, 101, 99, 102]
        wr = win_rate(nav)
        assert 0 <= wr <= 1

    def test_all_wins(self):
        nav = [100, 101, 102, 103]
        assert win_rate(nav) == 1.0

    def test_insufficient_data(self):
        assert win_rate([100]) == 0.0


class TestBeta:
    def test_equal_returns(self):
        nav = [100, 101, 102, 103]
        bench = [100, 101, 102, 103]
        b = beta(nav, bench)
        assert b == pytest.approx(1.0)

    def test_insufficient(self):
        assert beta([100], [100]) == 0.0


class TestAlpha:
    def test_zero_alpha(self):
        nav = [100, 101, 102]
        bench = [100, 101, 102]
        a = alpha(nav, bench, risk_free_rate=0.02)
        assert abs(a) < 0.01

    def test_insufficient(self):
        assert alpha([100], [100]) == 0.0


class TestInformationRatio:
    def test_equal(self):
        nav = [100, 101, 102, 103, 104]
        bench = [100, 101, 102, 103, 104]
        ir = information_ratio(nav, bench)
        assert abs(ir) < 1e-6

    def test_insufficient(self):
        assert information_ratio([100], [100]) == 0.0


class TestComputeAllMetrics:
    def test_returns_all_fields(self):
        nav = [100, 101, 102, 103, 104]
        bench = [100, 100.5, 101, 101.5, 102]
        metrics = compute_all_metrics(nav, benchmark_nav=bench)
        for field in [
            "cumulative_return", "annualized_return", "sharpe_ratio",
            "sortino_ratio", "max_drawdown", "win_rate",
            "beta", "alpha", "information_ratio",
        ]:
            assert field in metrics
