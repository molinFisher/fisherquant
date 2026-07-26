"""analytics/stats 统计量边界测试（P2 低覆盖补齐）。

覆盖 compute_mean / compute_variance / compute_std / compute_beta 的边界：
空序列、单点、全相等序列不抛异常且返回合理值。
"""
import math
import pytest
from fisher.analytics.stats import (
    compute_mean,
    compute_variance,
    compute_std,
    compute_beta,
)


class TestComputeMean:
    def test_empty(self):
        assert compute_mean([]) == 0.0

    def test_single(self):
        assert compute_mean([5.0]) == 5.0

    def test_basic(self):
        assert compute_mean([1.0, 2.0, 3.0]) == 2.0

    def test_all_equal(self):
        assert compute_mean([2.0, 2.0, 2.0]) == 2.0


class TestComputeVariance:
    def test_empty(self):
        assert compute_variance([]) == 0.0

    def test_single(self):
        # n < 2 无样本方差，约定返回 0.0
        assert compute_variance([5.0]) == 0.0

    def test_basic_sample_variance(self):
        # 样本方差（n-1）：((1)+(0)+(1))/2 = 1.0
        assert compute_variance([1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_all_equal_zero_variance(self):
        assert compute_variance([2.0, 2.0, 2.0, 2.0]) == 0.0


class TestComputeStd:
    def test_empty(self):
        assert compute_std([]) == 0.0

    def test_single(self):
        assert compute_std([5.0]) == 0.0

    def test_basic(self):
        # sqrt(样本方差 1.0) = 1.0
        assert compute_std([1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_all_equal_zero_std(self):
        # 全相等：std 必须为 0（不抛异常）
        assert compute_std([7.0, 7.0, 7.0]) == 0.0

    def test_std_equals_sqrt_variance(self):
        data = [0.1, 0.5, 0.9, 1.2]
        assert compute_std(data) == pytest.approx(math.sqrt(compute_variance(data)))


class TestComputeBeta:
    def test_empty_and_single_return_zero(self):
        # 任一序列长度 < 2 -> 0.0
        assert compute_beta([], []) == 0.0
        assert compute_beta([1.0], [1.0]) == 0.0

    def test_constant_benchmark_zero_beta(self):
        # 基准收益率为 0 方差 -> 无法估计 beta，返回 0.0
        assert compute_beta([1.0, 2.0, 3.0], [2.0, 2.0, 2.0]) == 0.0

    def test_perfect_positive_correlation(self):
        p = [1.0, 2.0, 3.0, 4.0]
        b = [1.0, 2.0, 3.0, 4.0]
        assert compute_beta(p, b) == pytest.approx(1.0)

    def test_perfect_negative_correlation(self):
        p = [1.0, 2.0, 3.0, 4.0]
        b = [4.0, 3.0, 2.0, 1.0]
        assert compute_beta(p, b) == pytest.approx(-1.0)

    def test_partial_movement(self):
        p = [1.0, 2.0, 4.0]
        b = [1.0, 2.0, 3.0]
        # 手工核对：mean_p=7/3, mean_b=2
        expected_cov = ((1-7/3)*(1-2) + (2-7/3)*(2-2) + (4-7/3)*(3-2)) / 2
        expected_var = ((1-2)**2 + (2-2)**2 + (3-2)**2) / 2
        expected = expected_cov / expected_var
        assert compute_beta(p, b) == pytest.approx(expected)

    def test_alignment_by_tail(self):
        # 长度不一致时按末尾对齐（n = min len）
        p = [99.0, 1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        # 取末尾 3 个：p'= [1,2,3], b'= [1,2,3] -> beta 1.0
        assert compute_beta(p, b) == pytest.approx(1.0)
