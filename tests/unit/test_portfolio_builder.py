import pytest
from fisher.event.types import Signal, OrderPending, OrderSide
from fisher.portfolio.builder import PortfolioBuilder
from fisher.portfolio.methods import equal_weight, risk_parity, kelly


def _make_signal(
    ticker="000001.SZ",
    side=OrderSide.BUY,
    quantity=100,
    confidence=1.0,
    reason="test",
    market="a_share",
    limit_price=10.0,
):
    return Signal(
        strategy="test",
        ticker=ticker,
        market=market,
        side=side,
        quantity=quantity,
        confidence=confidence,
        reason=reason,
        limit_price=limit_price,
    )


class TestWeightMethods:
    def test_equal_weight(self):
        merged = {"A": {}, "B": {}, "C": {}}
        weights = equal_weight(merged, 2)
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 0.001
        for w in weights.values():
            assert w == 0.5

    def test_equal_weight_empty(self):
        weights = equal_weight({}, 5)
        assert weights == {}

    def test_equal_weight_max_positions_limits(self):
        merged = {f"T{i}": {} for i in range(10)}
        weights = equal_weight(merged, 3)
        assert len(weights) == 3

    def test_risk_parity(self):
        merged = {"A": {}, "B": {}, "C": {}, "D": {}}
        weights = risk_parity(merged, 100000)
        assert len(weights) == 4
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_risk_parity_with_vol_data(self):
        merged = {"A": {"vol": 0.20}, "B": {"vol": 0.10}}
        weights = risk_parity(merged, 100000)
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 0.001
        assert weights["A"] < weights["B"]

    def test_risk_parity_empty(self):
        weights = risk_parity({}, 100000)
        assert weights == {}

    def test_kelly(self):
        merged = {"A": {}, "B": {}}
        weights = kelly(merged)
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_kelly_with_confidence(self):
        merged = {"A": {"confidence": 0.7, "win_loss_ratio": 2.0}, "B": {"confidence": 0.3, "win_loss_ratio": 1.0}}
        weights = kelly(merged)
        # 稳健凯利（P1-11）：f*_A = 0.7 - 0.3/2 = 0.55 → 截断 0.25 → 分数 0.5 = 0.125；
        # B 负 edge（f*<0）被剔除，不分配仓位。
        assert len(weights) == 1
        assert "A" in weights
        assert abs(weights["A"] - 0.125) < 0.01

    def test_kelly_empty(self):
        weights = kelly({})
        assert weights == {}


class TestPortfolioBuilder:
    def test_build_orders_equal_weight(self):
        builder = PortfolioBuilder(method="equal_weight", max_positions=3)
        signals = [
            _make_signal("A", OrderSide.BUY, 100, 0.9),
            _make_signal("B", OrderSide.BUY, 200, 0.8),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 2
        for o in orders:
            assert isinstance(o, OrderPending)
            assert o.price > 0

    def test_conflict_skip(self):
        builder = PortfolioBuilder(conflict_mode="skip_conflict")
        signals = [
            _make_signal("A", OrderSide.BUY, 100, 0.8),
            _make_signal("A", OrderSide.SELL, 50, 0.6),
            _make_signal("B", OrderSide.BUY, 100, 0.9),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].ticker == "B"

    def test_conflict_weighted_merge(self):
        builder = PortfolioBuilder(conflict_mode="weighted_merge")
        signals = [
            _make_signal("A", OrderSide.BUY, 100, 0.8),
            _make_signal("A", OrderSide.SELL, 50, 0.6),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].ticker == "A"

    def test_conflict_weighted_merge_nets_buy_sell(self):
        builder = PortfolioBuilder(conflict_mode="weighted_merge")
        signals = [
            _make_signal("A", OrderSide.BUY, 300, 0.8),
            _make_signal("A", OrderSide.SELL, 200, 0.6),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].ticker == "A"
        assert orders[0].side == OrderSide.BUY
        assert orders[0].quantity == 100

    def test_conflict_weighted_sell_dominates(self):
        builder = PortfolioBuilder(conflict_mode="weighted_merge")
        signals = [
            _make_signal("A", OrderSide.BUY, 50, 0.3),
            _make_signal("A", OrderSide.SELL, 100, 0.8),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.SELL
        assert orders[0].quantity == 50

    def test_conflict_first_wins(self):
        builder = PortfolioBuilder(conflict_mode="first_wins")
        signals = [
            _make_signal("A", OrderSide.BUY, 100, 0.8),
            _make_signal("A", OrderSide.SELL, 50, 0.9),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY

    def test_max_positions_enforced(self):
        builder = PortfolioBuilder(method="equal_weight", max_positions=2)
        signals = [
            _make_signal("A", OrderSide.BUY, 100, 1.0),
            _make_signal("B", OrderSide.BUY, 100, 1.0),
            _make_signal("C", OrderSide.BUY, 100, 1.0),
            _make_signal("D", OrderSide.BUY, 100, 1.0),
        ]
        orders = builder.build_orders(signals, 100000)
        assert len(orders) == 2

    def test_empty_signals_returns_empty(self):
        builder = PortfolioBuilder()
        orders = builder.build_orders([], 100000)
        assert orders == []

    def test_allocation_adds_to_capital(self):
        builder = PortfolioBuilder(method="equal_weight", max_positions=4)
        # 信号数量足够大（≥ 单标分配额/价格），使下单数量不被权重分配额截断，
        # 从而总部署资金 ≈ 全部本金。
        signals = [
            _make_signal("A", OrderSide.BUY, 10000, 1.0),
            _make_signal("B", OrderSide.BUY, 10000, 1.0),
        ]
        orders = builder.build_orders(signals, 100000)
        total_allocation = sum(o.price * o.quantity for o in orders)
        assert abs(total_allocation - 100000) < 0.01
