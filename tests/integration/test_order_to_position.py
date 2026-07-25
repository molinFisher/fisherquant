import pytest
from fisher.event.types import Bar, OrderSide, OrderStatus
from fisher.oms.orders import create_order
from fisher.oms.engine import OMSEngine
from fisher.paper.engine import PaperEngine
from fisher.position.service import PositionService
from fisher.risk.engine import RiskEngine
from fisher.risk.pre_trade import MaxPositionRule, DailyLossLimitRule, BlacklistRule
from fisher.config.schemas import AssetFeeConfig

A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025,
    min_commission=5.0,
    stamp_duty=0.0005,
    stamp_duty_side="sell",
    transfer_fee=0.00001,
    regulatory_fee=0.0000687,
)


class TestOrderToPositionPipeline:
    def test_oms_to_paper_to_position(self):
        oms = OMSEngine()
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()

        order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        oms.submit(order)
        oms.update_status(order.order_id, OrderStatus.SUBMITTED)
        paper.submit_order(order)

        bar = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=9.9, high=10.1, low=9.8, close=10.0,
            volume=100000, amount=1000000.0, bar_time=1234567890.0,
        )

        filled = paper.on_bar(bar)
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.FILLED

        positions.update_on_fill(filled[0], 10.0)

        pos = positions.get_position("000001.SZ")
        assert pos is not None
        assert pos["quantity"] == 100
        assert pos["avg_cost"] > 0

    def test_full_pipeline_with_risk_check(self):
        oms = OMSEngine()
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()
        risk = RiskEngine(rules=[
            MaxPositionRule(max_pct=0.2),
            DailyLossLimitRule(max_loss_pct=0.05),
        ])

        order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        approved, reasons = risk.check(order, positions, 100000.0)
        assert approved, f"Risk check failed: {reasons}"

        oms.submit(order)
        oms.update_status(order.order_id, OrderStatus.SUBMITTED)
        paper.submit_order(order)

        bar = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=10.0, high=10.2, low=9.9, close=10.0,
            volume=100000, amount=1000000.0, bar_time=1234567890.0,
        )
        filled = paper.on_bar(bar)
        assert len(filled) == 1

        positions.update_on_fill(filled[0], 10.0)
        pos = positions.get_position("000001.SZ")
        assert pos is not None

    def test_risk_rejects_oversized_order(self):
        positions = PositionService()
        risk = RiskEngine(rules=[MaxPositionRule(max_pct=0.1)])

        order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 50.0)
        approved, reasons = risk.check(order, positions, 50000.0)
        assert approved is True

        big_order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 200, 100.0)
        approved, reasons = risk.check(big_order, positions, 50000.0)
        assert approved is False

    def test_multiple_orders_same_ticker_t_plus(self):
        oms = OMSEngine()
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()

        o1 = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        oms.submit(o1)
        oms.update_status(o1.order_id, OrderStatus.SUBMITTED)
        paper.submit_order(o1)

        bar = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=10.0, high=10.2, low=9.9, close=10.0,
            volume=100000, amount=1000000.0, bar_time=1234567890.0,
        )
        paper.on_bar(bar)
        positions.update_on_fill(o1, 10.0)

        pos = positions.get_position("000001.SZ")
        assert pos["available"] == 0  # T+1 blocked

        positions.settle_t1()
        pos = positions.get_position("000001.SZ")
        assert pos["available"] == 100

    def test_sell_order_reduces_position(self):
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()

        buy = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 200, 10.0)
        paper.submit_order(buy)
        bar = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=10.0, high=10.2, low=9.9, close=10.0,
            volume=100000, amount=1000000.0, bar_time=1,
        )
        paper.on_bar(bar)
        positions.update_on_fill(buy, 10.0)

        positions.settle_t1()

        sell = create_order("000001.SZ", "a_share", "stock", OrderSide.SELL, 100, 11.0)
        paper.submit_order(sell)
        bar2 = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=11.0, high=11.2, low=10.9, close=11.0,
            volume=100000, amount=1000000.0, bar_time=2,
        )
        paper.on_bar(bar2)
        positions.update_on_fill(sell, 11.0)

        pos = positions.get_position("000001.SZ")
        assert pos["quantity"] == 100

    def test_blacklist_rejects_order(self):
        risk = RiskEngine(rules=[BlacklistRule(blacklist=["000002.SZ"])])
        order = create_order("000002.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        approved, reasons = risk.check(order, None, 100000.0)
        assert approved is False
        assert "Blacklist" in reasons[0]
