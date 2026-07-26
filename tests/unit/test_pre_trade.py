"""逐条规则的显式命中/未命中断言测试：fisher/risk/pre_trade.py。

在既有 test_risk_engine.py 基础上，针对每条 PreTradeRule 补充边界值（恰好等于上限、
恰好低于上限）与精确原因字符串的强断言，强化覆盖。
"""
import pytest

from fisher.event.types import OrderSide
from fisher.oms.orders import create_order
from fisher.position.service import PositionService
from fisher.risk.pre_trade import (
    MaxPositionRule,
    DailyLossLimitRule,
    PriceLimitRule,
    BlacklistRule,
    SectorLimitRule,
)


def _order(ticker="000001.SZ", side=OrderSide.BUY, quantity=100, price=10.0, market="a_share"):
    return create_order(ticker, market, "stock", side, quantity, price)


def _pos_svc(positions: dict[str, int] | None = None):
    svc = PositionService()
    if positions:
        for ticker, qty in positions.items():
            o = _order(ticker, quantity=qty, price=10.0)
            o.filled_qty = qty
            o.filled_price = 10.0
            o.commission = 0.0
            svc.update_on_fill(o, 10.0)
    return svc


class TestMaxPositionRuleExplicit:
    def test_boundary_equal_to_limit_is_approved(self):
        # capital=100000, max_pct=0.2 -> 上限 20000；恰好等于上限应放行
        rule = MaxPositionRule(max_pct=0.2)
        order = _order(quantity=2000, price=10.0)  # 2000*10 = 20000
        approved, reason = rule.check(order, _pos_svc(), 100000.0)
        assert approved is True
        assert reason == ""

    def test_boundary_one_cent_over_limit_rejected(self):
        rule = MaxPositionRule(max_pct=0.2)
        order = _order(quantity=2001, price=10.0)  # 20010 > 20000
        approved, reason = rule.check(order, _pos_svc(), 100000.0)
        assert approved is False
        assert "MaxPosition" in reason

    def test_existing_position_combined_boundary(self):
        rule = MaxPositionRule(max_pct=0.2)
        svc = _pos_svc({"000001.SZ": 1000})  # 现有市值 1000*10 = 10000
        # 新单 1000*10=10000，合计 20000 == 上限 -> 放行
        order = _order("000001.SZ", quantity=1000, price=10.0)
        approved, _ = rule.check(order, svc, 100000.0)
        assert approved is True
        # 合计 20001 -> 拒单
        order = _order("000001.SZ", quantity=1001, price=10.0)
        approved, reason = rule.check(order, svc, 100000.0)
        assert approved is False
        assert "20000" in reason or "20010" in reason

    def test_no_position_service_treats_existing_zero(self):
        rule = MaxPositionRule(max_pct=0.2)
        order = _order(quantity=2000, price=10.0)
        approved, _ = rule.check(order, None, 100000.0)
        assert approved is True


class TestDailyLossLimitRuleExplicit:
    def test_boundary_exact_limit_rejected(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule._cumulative_pnl = -5000.0  # 恰好 5% on 100000
        order = _order()
        approved, reason = rule.check(order, _pos_svc(), 100000.0)
        assert approved is False
        assert "DailyLossLimit" in reason

    def test_boundary_just_under_limit_approved(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule._cumulative_pnl = -4999.0  # 4.999% < 5%
        order = _order()
        approved, _ = rule.check(order, _pos_svc(), 100000.0)
        assert approved is True

    def test_positive_pnl_never_blocks(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule._cumulative_pnl = 3000.0  # 盈利不应触发
        order = _order()
        approved, _ = rule.check(order, _pos_svc(), 100000.0)
        assert approved is True

    def test_record_pnl_accumulates_and_reset_clears(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule.record_pnl(-3000.0)
        rule.record_pnl(-2000.0)
        assert rule._cumulative_pnl == -5000.0
        rule.reset_daily_pnl()
        assert rule._cumulative_pnl == 0.0

    def test_zero_capital_no_division_error(self):
        rule = DailyLossLimitRule(max_loss_pct=0.05)
        rule._cumulative_pnl = -5000.0
        approved, _ = rule.check(_order(), _pos_svc(), 0.0)
        assert approved is True


class TestPriceLimitRuleExplicit:
    def test_buy_boundary_upper_approved(self):
        rule = PriceLimitRule(upper=0.095)
        order = _order(price=10.0)
        # 市价 10.95 -> +9.5% 恰好等于上限 -> 放行
        approved, _ = rule.check(order, None, 100000.0, market_price=10.95)
        assert approved is True

    def test_buy_over_upper_rejected(self):
        rule = PriceLimitRule(upper=0.095)
        order = _order(price=10.0)
        approved, reason = rule.check(order, None, 100000.0, market_price=10.96)
        assert approved is False
        assert "PriceLimit" in reason

    def test_sell_boundary_lower_approved(self):
        rule = PriceLimitRule(lower=-0.095)
        order = _order(side=OrderSide.SELL, price=10.0)
        # 市价 9.05 -> -9.5% 恰好等于下限 -> 放行
        approved, _ = rule.check(order, None, 100000.0, market_price=9.05)
        assert approved is True

    def test_sell_below_lower_rejected(self):
        rule = PriceLimitRule(lower=-0.095)
        order = _order(side=OrderSide.SELL, price=10.0)
        approved, reason = rule.check(order, None, 100000.0, market_price=9.04)
        assert approved is False
        assert "down" in reason

    def test_nonpositive_market_price_skips_check(self):
        rule = PriceLimitRule(upper=0.001)  # 极严上限
        order = _order(price=10.0)
        # market_price<=0 时跳过检查，放行
        approved, _ = rule.check(order, None, 100000.0, market_price=0.0)
        assert approved is True


class TestSectorLimitRuleExplicit:
    def test_ticker_without_sector_map_approved(self):
        rule = SectorLimitRule(max_pct=0.3, sector_map={})
        order = _order(quantity=1000, price=10.0)
        approved, _ = rule.check(order, _pos_svc(), 100000.0)
        assert approved is True

    def test_boundary_equal_to_sector_limit_approved(self):
        rule = SectorLimitRule(max_pct=0.2, sector_map={"000001.SZ": "tech"})
        # 无现有持仓，新单市值恰好等于上限 20000 -> 放行
        order = _order("000001.SZ", quantity=2000, price=10.0)
        approved, _ = rule.check(order, _pos_svc(), 100000.0)
        assert approved is True

    def test_over_sector_limit_rejected(self):
        rule = SectorLimitRule(max_pct=0.2, sector_map={"000001.SZ": "tech"})
        order = _order("000001.SZ", quantity=2001, price=10.0)  # 20010 > 20000
        approved, reason = rule.check(order, _pos_svc(), 100000.0)
        assert approved is False
        assert "SectorLimit" in reason

    def test_existing_sector_exposure_counts(self):
        rule = SectorLimitRule(max_pct=0.2, sector_map={"000001.SZ": "tech", "000002.SZ": "tech"})
        svc = _pos_svc({"000001.SZ": 1000})  # 现有 tech 市值 10000
        svc.mark_to_market({"000001.SZ": 10.0})
        # 新单 000001 同 sector，合计 10000 + 10000 = 20000 == 上限 -> 放行
        order = _order("000001.SZ", quantity=1000, price=10.0)
        approved, _ = rule.check(order, svc, 100000.0)
        assert approved is True
        # 合计 20010 -> 拒单
        order = _order("000001.SZ", quantity=1001, price=10.0)
        approved, reason = rule.check(order, svc, 100000.0)
        assert approved is False


class TestBlacklistRuleExplicit:
    def test_blacklisted_rejected_with_reason(self):
        rule = BlacklistRule(blacklist=["000001.SZ"])
        approved, reason = rule.check(_order("000001.SZ"), None, 100000.0)
        assert approved is False
        assert "Blacklist" in reason

    def test_not_blacklisted_approved(self):
        rule = BlacklistRule(blacklist=["000002.SZ"])
        approved, reason = rule.check(_order("000001.SZ"), None, 100000.0)
        assert approved is True
        assert reason == ""
