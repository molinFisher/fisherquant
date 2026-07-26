"""强断言测试：fisher/risk/realtime.py（RealtimeRiskMonitor 实时拦截路径）。

覆盖：
- add_return 累积收益序列
- var() 在样本不足 / 足量时的返回（含 99% 置信度下的定量校验）
- beta() 在基准平坦 / 已知相关序列下的计算
- max_drawdown(nav_series) 的峰谷回撤定量
- check_drawdown：新高放行并更新峰值；跌破阈值拒单（带百分比告警）；阈值内放行
- check_beta：超阈拒单（带告警）；阈值内放行；边界（等于上限时放行）
- 端到端实时拦截：下跌序列触发拒单、恢复序列放行
"""
import math

import pytest

from fisher.risk.realtime import RealtimeRiskMonitor


def _monitor(**kwargs) -> RealtimeRiskMonitor:
    return RealtimeRiskMonitor(**kwargs)


class TestAddReturnAndVar:
    def test_var_returns_zero_when_fewer_than_two_returns(self):
        m = _monitor()
        assert m.var() == 0.0
        m.add_return(0.01)
        assert m.var() == 0.0

    def test_var_quantitative_at_99_confidence(self):
        # 99% 置信度 -> idx = int(N*0.01)；N=7 时取排序后最小（最极端亏损）
        m = _monitor(var_confidence=0.99)
        for r in [-0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]:
            m.add_return(r)
        # 排序后 idx=0 -> -0.05 -> abs = 0.05
        assert m.var() == pytest.approx(0.05, abs=1e-9)

    def test_var_decreases_with_more_extreme_tail(self):
        m = _monitor(var_confidence=0.99)
        for r in [-0.10, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]:
            m.add_return(r)
        assert m.var() == pytest.approx(0.10, abs=1e-9)

    def test_benchmark_return_is_stored_separately(self):
        m = _monitor()
        m.add_return(0.01, 0.005)
        m.add_return(0.02, 0.01)
        # returns 列表应只含组合收益
        assert m._as_list(m._returns) == [0.01, 0.02]
        assert m._as_list(m._benchmark_returns) == [0.005, 0.01]


class TestBeta:
    def test_beta_zero_when_benchmark_flat(self):
        m = _monitor()
        # 默认基准收益为 0 -> 基准方差为 0 -> beta 定义为 0
        for p in [0.01, -0.02, 0.03, -0.01]:
            m.add_return(p, 0.0)
        assert m.beta() == 0.0

    def test_beta_known_proportional_series(self):
        m = _monitor()
        rp = [0.01, 0.02, 0.03, 0.04]
        rb = [0.005, 0.01, 0.015, 0.02]  # 组合收益 = 2 * 基准收益
        for p, b in zip(rp, rb):
            m.add_return(p, b)
        assert m.beta() == pytest.approx(2.0, abs=1e-9)

    def test_beta_negative_correlation(self):
        m = _monitor()
        rp = [0.02, -0.01, 0.03, -0.02]
        rb = [-0.01, 0.005, -0.015, 0.01]  # 组合 = -2 * 基准
        for p, b in zip(rp, rb):
            m.add_return(p, b)
        assert m.beta() == pytest.approx(-2.0, abs=1e-9)


class TestMaxDrawdown:
    def test_empty_series_returns_zero(self):
        m = _monitor()
        assert m.max_drawdown([]) == 0.0

    def test_max_drawdown_quantitative(self):
        m = _monitor()
        nav = [100, 110, 105, 120, 90, 130]
        # 峰 120 -> 谷 90，回撤 (120-90)/120 = 0.25
        assert m.max_drawdown(nav) == pytest.approx(0.25, abs=1e-9)

    def test_max_drawdown_monotonic_up_is_zero(self):
        m = _monitor()
        assert m.max_drawdown([100, 101, 102, 103]) == 0.0

    def test_max_drawdown_does_not_alter_running_peak(self):
        m = _monitor()
        m.max_drawdown([100, 80, 90])
        # 独立的 nav 序列计算不应修改实时拦截用的 _peak_nav
        assert m._peak_nav == 0.0


class TestCheckDrawdown:
    def test_new_high_is_approved_and_updates_peak(self):
        m = _monitor(max_drawdown=0.15)
        approved, reason = m.check_drawdown(100.0)
        assert approved is True
        assert reason == ""
        assert m._peak_nav == 100.0

    def test_within_drawdown_still_approved(self):
        m = _monitor(max_drawdown=0.15)
        m.check_drawdown(100.0)  # peak -> 100
        approved, reason = m.check_drawdown(95.0)  # dd=(100-95)/100=5% < 15%
        assert approved is True
        assert reason == ""

    def test_breach_drawdown_rejected_with_alert(self):
        m = _monitor(max_drawdown=0.15)
        m.check_drawdown(100.0)  # peak -> 100
        m.check_drawdown(110.0)  # peak -> 110
        approved, reason = m.check_drawdown(90.0)  # dd=(110-90)/110≈18.18% >= 15%
        assert approved is False
        assert "18.18%" in reason
        assert "15.00%" in reason

    def test_custom_threshold_boundary(self):
        # max_drawdown=0.05：跌破 5% 拒单，恰好 4% 放行
        m = _monitor(max_drawdown=0.05)
        m.check_drawdown(100.0)
        assert m.check_drawdown(96.0)[0] is True   # dd = 4%
        assert m.check_drawdown(94.0)[0] is False  # dd = 6%

    def test_recovery_after_drawdown_resets_peak(self):
        m = _monitor(max_drawdown=0.15)
        m.check_drawdown(100.0)
        m.check_drawdown(110.0)
        assert m.check_drawdown(90.0)[0] is False
        # 创新高后，新的回撤从新峰值算起，应放行
        assert m.check_drawdown(115.0)[0] is True
        assert m._peak_nav == 115.0


class TestCheckBeta:
    def test_within_limit_approved(self):
        m = _monitor(beta_limit=1.5)
        assert m.check_beta(1.0) == (True, "")

    def test_above_limit_rejected_with_alert(self):
        m = _monitor(beta_limit=1.5)
        approved, reason = m.check_beta(2.0)
        assert approved is False
        assert "2.00" in reason
        assert "1.50" in reason

    def test_negative_beta_abs_compared(self):
        m = _monitor(beta_limit=1.5)
        # abs(-2.0)=2.0 > 1.5 -> 拒单
        assert m.check_beta(-2.0)[0] is False

    def test_boundary_equal_limit_passes(self):
        m = _monitor(beta_limit=1.5)
        # 等于上限不算超出
        assert m.check_beta(1.5) == (True, "")


class TestRealtimeInterceptionFlow:
    def test_drawdown_breach_then_recovery_flow(self):
        m = _monitor(max_drawdown=0.10, beta_limit=1.5)
        # 上升阶段均放行
        for nav in [100, 102, 105, 108]:
            assert m.check_drawdown(nav)[0] is True
        # 急跌触发拒单
        assert m.check_drawdown(95.0)[0] is False  # dd=(108-95)/108≈12% > 10%
        # 小幅回升但仍在回撤中仍放行（未超阈）
        assert m.check_drawdown(100.0)[0] is True
        # beta 同时超阈则拒单
        assert m.check_beta(1.8)[0] is False

    def test_beta_gate_independent_of_drawdown(self):
        m = _monitor(max_drawdown=0.15, beta_limit=1.0)
        # 净值平稳（无回撤），但 beta 超阈 -> 拒单
        m.check_drawdown(100.0)
        assert m.check_drawdown(100.0)[0] is True
        assert m.check_beta(1.2)[0] is False


class TestPeakNavFromSeries:
    def test_returns_max_when_nonempty(self):
        m = _monitor()
        assert m._peak_nav_from_series([1.0, 3.0, 2.0, 0.5]) == pytest.approx(3.0)

    def test_returns_zero_when_empty(self):
        m = _monitor()
        assert m._peak_nav_from_series([]) == 0.0
