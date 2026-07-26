"""属性测试 + 强断言：fisher/portfolio/methods.py。

使用 hypothesis 做属性测试：
- equal_weight：Σweights ≈ 1（容差 1e-6），选中数 = min(max_positions, 资产数)
- risk_parity（独立假设逆波动率加权）：Σweights ≈ 1，且各资产风险贡献两两差 < 1e-3
- kelly：权重 ≥ 0 且总和 ≤ 1（不向上归一化）

并补充确定性强断言：
- risk_parity 逆波动率定性（高波动资产权重更低）
- kelly 不向上归一化（强正期望时总仓 < 1）
- kelly 剔除负 edge 标的
- risk_parity 带协方差矩阵（ERC 迭代）风险贡献两两相等
"""
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from fisher.portfolio.methods import equal_weight, risk_parity, kelly


# --------------------------------------------------------------------------
# 属性测试（hypothesis）
# --------------------------------------------------------------------------

@settings(max_examples=60, deadline=None)
@given(
    confs=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1, max_size=8,
    ),
    maxpos=st.integers(min_value=1, max_value=10),
)
def test_prop_equal_weight_sums_to_one(confs, maxpos):
    merged = {f"T{i}": {"confidence": c} for i, c in enumerate(confs)}
    weights = equal_weight(merged, maxpos)
    expected_len = min(maxpos, len(merged))
    assert len(weights) == expected_len
    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-6
    for w in weights.values():
        assert w > 0.0
        assert abs(w - 1.0 / expected_len) < 1e-9


@settings(max_examples=60, deadline=None)
@given(
    vols=st.lists(
        st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False),
        min_size=2, max_size=6,
    ),
)
def test_prop_risk_parity_equal_risk_contribution(vols):
    merged = {f"T{i}": {"vol": v} for i, v in enumerate(vols)}
    weights = risk_parity(merged, capital=100000.0)
    assert len(weights) == len(vols)
    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-6
    # 独立假设下逆波动率加权 -> 资产风险贡献 w_i*vol_i 两两相等
    contributions = [weights[f"T{i}"] * vols[i] for i in range(len(vols))]
    for a in contributions:
        for b in contributions:
            assert abs(a - b) < 1e-3


@settings(max_examples=60, deadline=None)
@given(
    confidences=st.lists(
        st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
        min_size=1, max_size=6,
    ),
    wls=st.lists(
        st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False),
        min_size=1, max_size=6,
    ),
)
def test_prop_kelly_weights_bounded(confidences, wls):
    n = min(len(confidences), len(wls))
    merged = {
        f"T{i}": {"confidence": confidences[i], "win_loss_ratio": wls[i]}
        for i in range(n)
    }
    weights = kelly(merged)
    assert len(weights) <= n
    total = sum(weights.values())
    # 权重非负且总仓不超过 100%（不向上归一化 / 不加杠杆）
    assert total >= 0.0
    assert total <= 1.0 + 1e-9
    for w in weights.values():
        assert w >= 0.0


# --------------------------------------------------------------------------
# 确定性强断言
# --------------------------------------------------------------------------

class TestEqualWeightDeterministic:
    def test_selects_top_n_by_confidence(self):
        merged = {
            "A": {"confidence": 0.5},
            "B": {"confidence": 0.9},
            "C": {"confidence": 0.2},
        }
        weights = equal_weight(merged, 2)
        assert set(weights.keys()) == {"B", "A"}  # 前两高置信度
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_empty_returns_empty(self):
        assert equal_weight({}, 5) == {}


class TestRiskParityDeterministic:
    def test_inverse_vol_weighting_ordering(self):
        merged = {"A": {"vol": 0.20}, "B": {"vol": 0.10}}
        weights = risk_parity(merged, capital=100000.0)
        # 高波动资产应获得更低权重
        assert weights["A"] < weights["B"]
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_risk_contributions_equal(self):
        merged = {"A": {"vol": 0.20}, "B": {"vol": 0.10}, "C": {"vol": 0.30}}
        weights = risk_parity(merged, capital=100000.0)
        vols = {"A": 0.20, "B": 0.10, "C": 0.30}
        contribs = [weights[t] * vols[t] for t in vols]
        for a in contribs:
            for b in contribs:
                assert abs(a - b) < 1e-6

    def test_with_covariance_matrix_erc(self):
        # 提供协方差矩阵 -> 真正等风险贡献（ERC）迭代
        merged = {"A": {"vol": 0.20}, "B": {"vol": 0.10}}
        cov = {"A": {"A": 0.0, "B": 0.05}, "B": {"A": 0.05, "B": 0.0}}
        weights = risk_parity(merged, capital=100000.0, cov=cov)
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        # 实际风险贡献 RC_i = w_i * (Sigma w)_i 应两两相等
        tickers = ["A", "B"]
        vols = np.array([0.20, 0.10])
        Sigma = np.array([[0.04, 0.05], [0.05, 0.01]])
        w = np.array([weights["A"], weights["B"]])
        rc = w * (Sigma @ w)
        assert abs(rc[0] - rc[1]) < 1e-3


class TestKellyDeterministic:
    def test_no_upward_normalization(self):
        # 两个强正期望标的，f* 各 0.125，合计 0.25 < 1，不应向上归一化到 1
        merged = {
            "A": {"confidence": 0.7, "win_loss_ratio": 2.0},
            "B": {"confidence": 0.7, "win_loss_ratio": 2.0},
        }
        weights = kelly(merged)
        assert abs(weights["A"] - 0.125) < 1e-9
        assert abs(weights["B"] - 0.125) < 1e-9
        total = sum(weights.values())
        assert abs(total - 0.25) < 1e-9
        assert total < 1.0  # 关键：不向上归一化

    def test_negative_edge_dropped(self):
        merged = {
            "A": {"confidence": 0.3, "win_loss_ratio": 1.0},  # f* = -0.4 -> 剔除
            "B": {"confidence": 0.7, "win_loss_ratio": 2.0},  # f* = 0.55 -> 0.125
        }
        weights = kelly(merged)
        assert set(weights.keys()) == {"B"}
        assert abs(weights["B"] - 0.125) < 1e-9

    def test_per_asset_cap_respected(self):
        # 超高置信度也不得超过 max_per_asset(0.25)*fraction(0.5)=0.125
        merged = {"A": {"confidence": 0.99, "win_loss_ratio": 10.0}}
        weights = kelly(merged)
        assert weights["A"] <= 0.125 + 1e-12

    def test_high_confidence_gets_higher_weight(self):
        # 选用未触顶 max_per_asset 上限的置信度，避免被截断到同一上限
        merged = {
            "A": {"confidence": 0.45, "win_loss_ratio": 2.0},  # f*≈0.175 -> 0.0875
            "B": {"confidence": 0.40, "win_loss_ratio": 2.0},  # f*≈0.100 -> 0.0500
        }
        weights = kelly(merged)
        assert weights["A"] > weights["B"]

    def test_empty_returns_empty(self):
        assert kelly({}) == {}
