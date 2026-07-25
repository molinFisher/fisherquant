import pytest
from fisher.event.types import OrderSide
from fisher.oms.orders import Order, create_order
from fisher.risk.engine import RiskEngine
from fisher.risk.pre_trade import (
    MaxPositionRule,
    DailyLossLimitRule,
    PriceLimitRule,
    BlacklistRule,
)
from fisher.position.service import PositionService


def _make_order(ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, price=10.0):
    return create_order(ticker, market, "stock", side, quantity, price)


def _make_positions_svc(positions: dict[str, dict] | None = None):
    svc = PositionService()
    if positions:
        for ticker, qty in positions.items():
            order = _make_order(ticker, quantity=qty, price=10.0)
            order.filled_qty = qty
            order.filled_price = 10.0
            order.commission = 0.0
            svc.update_on_fill(order, 10.0)
    return svc


class TestMaxPositionRule:
    def test_under_limit_approved(self):
        rule = MaxPositionRule(max_pct=0.2)
        pos_svc = _make_positions_svc({"000001.SZ": 100})
        order = _make_order("000002.SZ", quantity=50, price=10.0)
        approved, reason = rule.check(order, pos_svc, 100000.0)
        assert approved is True

    def test_over_limit_rejected(self):
        rule = MaxPositionRule(max_pct=0.2)
        pos_svc = _make_positions_svc()
        order = _make_order("000001.SZ", quantity=500, price=50.0)
        approved, reason = rule.check(order, pos_svc, 100000.0)
        assert approved is False
        assert "MaxPosition" in reason

    def test_existing_position_combined_limits(self):
        rule = MaxPositionRule(max_pct=0.2)
        pos_svc = _make_positions_svc({"000001.SZ": 100})
        order = _make_order("000001.SZ", quantity=100, price=10.0)
        approved, reason = rule.check(order, pos_svc, 15000.0)
        assert approved is True

    def test_existing_position_combined_over_limit(self):
        rule = MaxPositionRule(max_pct=0.2)
        pos_svc = _make_positions_svc({"000001.SZ": 100})
        order = _make_order("000001.SZ", quantity=100, price=10.0)
        approved, reason = rule.check(order, pos_svc, 5000.0)
        assert approved is False


class TestDailyLossLimitRule:
    def test_no_loss_approved(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        pos_svc = _make_positions_svc()
        order = _make_order()
        rule.reset_daily_pnl()
        approved, reason = rule.check(order, pos_svc, 100000.0)
        assert approved is True

    def test_loss_within_limit_approved(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        pos_svc = _make_positions_svc()
        rule._cumulative_pnl = -4000.0  # -4% on 100k
        order = _make_order()
        approved, reason = rule.check(order, pos_svc, 100000.0)
        assert approved is True

    def test_loss_exceeds_limit_rejected(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        pos_svc = _make_positions_svc()
        rule._cumulative_pnl = -6000.0  # -6% on 100k
        order = _make_order()
        approved, reason = rule.check(order, pos_svc, 100000.0)
        assert approved is False

    def test_reset_daily_pnl(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule._cumulative_pnl = -6000.0
        rule.reset_daily_pnl()
        assert rule._cumulative_pnl == 0.0


class TestPriceLimitRule:
    def test_within_limit_approved(self):
        rule = PriceLimitRule()
        order = _make_order("000001.SZ", price=10.0)
        approved, reason = rule.check(order, None, 100000.0)
        assert approved is True

    def test_buy_limit_price_check(self):
        rule = PriceLimitRule(upper=0.095)
        order = _make_order(price=10.0)
        assert rule._check_price_limit(order, 10.9) is True
        assert rule._check_price_limit(order, 11.0) is False


class TestBlacklistRule:
    def test_not_blacklisted_approved(self):
        rule = BlacklistRule(blacklist=["000002.SZ"])
        order = _make_order("000001.SZ")
        approved, reason = rule.check(order, None, 100000.0)
        assert approved is True

    def test_blacklisted_rejected(self):
        rule = BlacklistRule(blacklist=["000001.SZ"])
        order = _make_order("000001.SZ")
        approved, reason = rule.check(order, None, 100000.0)
        assert approved is False


class TestRiskEngine:
    def test_empty_rules_approved(self):
        engine = RiskEngine(rules=[])
        order = _make_order()
        approved, reasons = engine.check(order, None, 100000.0)
        assert approved is True
        assert reasons == []

    def test_all_rules_match_approved(self):
        engine = RiskEngine(rules=[
            MaxPositionRule(max_pct=0.2),
            DailyLossLimitRule(max_loss_pct=0.05),
        ])
        pos_svc = _make_positions_svc()
        order = _make_order(quantity=10, price=10.0)
        approved, reasons = engine.check(order, pos_svc, 100000.0)
        assert approved is True

    def test_one_rule_rejects_overall_rejected(self):
        engine = RiskEngine(rules=[
            MaxPositionRule(max_pct=0.2),
            BlacklistRule(blacklist=["000001.SZ"]),
        ])
        order = _make_order("000001.SZ", quantity=100, price=50.0)
        approved, reasons = engine.check(order, None, 100000.0)
        assert approved is False
        assert len(reasons) == 1

    def test_multiple_rules_reject(self):
        engine = RiskEngine(rules=[
            MaxPositionRule(max_pct=0.1),
            BlacklistRule(blacklist=["000001.SZ"]),
        ])
        order = _make_order("000001.SZ", quantity=100, price=50.0)
        approved, reasons = engine.check(order, None, 9000.0)
        assert approved is False
        assert len(reasons) == 2

    def test_engine_runs_all_rules_even_after_rejection(self):
        counts = []
        class CountingRule(MaxPositionRule):
            def check(self, order, pos_svc, capital):
                counts.append(1)
                return super().check(order, pos_svc, capital)

        engine = RiskEngine(rules=[
            CountingRule(max_pct=0.2),
            CountingRule(max_pct=0.2),
            CountingRule(max_pct=0.2),
        ])
        order = _make_order()
        engine.check(order, None, 100000.0)
        assert len(counts) == 3
