import pytest
from fisher.event.types import Bar, OrderSide, OrderStatus
from fisher.oms.orders import Order, create_order
from fisher.paper.fees import FeeCalculator
from fisher.paper.fill import FillSimulator
from fisher.paper.engine import PaperEngine
from fisher.market.rules import AShareRules
from fisher.config.schemas import AssetFeeConfig


A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025,
    min_commission=5.0,
    stamp_duty=0.0005,
    stamp_duty_side="sell",
    transfer_fee=0.00001,
    regulatory_fee=0.0000687,
)


def _make_order(ticker="000001.SZ", side=OrderSide.BUY, quantity=100, price=10.0):
    return create_order(ticker, "a_share", "stock", side, quantity, price)


def _make_bar(ticker="000001.SZ", open=10.0, close=10.2, volume=100000, amount=1000000.0):
    return Bar(
        ticker=ticker, market="a_share", frequency="1d",
        open=open, high=max(open, close), low=min(open, close), close=close,
        volume=volume, amount=amount, bar_time=1234567890.0,
    )


class TestPaperEngineSubmit:
    def test_submit_order_retains_order_id(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order()
        result = engine.submit_order(order)
        assert result.order_id == order.order_id

    def test_submit_order_goes_to_pending(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order()
        submitted = engine.submit_order(order)
        assert submitted.status == OrderStatus.PENDING

    def test_submit_twice_raises(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order()
        engine.submit_order(order)
        with pytest.raises(ValueError, match="already submitted"):
            engine.submit_order(order)

    def test_get_order_after_submit(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order()
        engine.submit_order(order)
        found = engine.get_order(order.order_id)
        assert found is not None
        assert found.order_id == order.order_id

    def test_get_order_not_found(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        assert engine.get_order("nonexistent") is None


class TestPaperEngineCancel:
    def test_cancel_order(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order()
        engine.submit_order(order)
        result = engine.cancel_order(order.order_id)
        assert result is True
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_nonexistent(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        result = engine.cancel_order("nonexistent")
        assert result is False


class TestPaperEngineOnBarFill:
    def test_on_bar_fills_order(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order(side=OrderSide.BUY, quantity=100, price=10.0)
        engine.submit_order(order)
        bar = _make_bar(open=9.9, close=10.0, volume=100000)
        # P0-2：提交当根 bar 的订单延迟一根 bar 成交，故需第二根 bar 才撮合
        engine.on_bar(bar)
        filled = engine.on_bar(bar)
        assert len(filled) == 1
        assert filled[0].order_id == order.order_id
        assert order.status == OrderStatus.FILLED

    def test_on_bar_without_matching_orders(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order(ticker="000001.SZ", price=10.0)
        engine.submit_order(order)
        bar = _make_bar(ticker="000002.SZ")  # different ticker
        filled = engine.on_bar(bar)
        assert len(filled) == 0

    def test_on_bar_sell_order_fills(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order(side=OrderSide.SELL, quantity=100, price=10.0)
        engine.submit_order(order)
        bar = _make_bar(open=10.0, close=10.0, volume=100000)
        engine.on_bar(bar)
        filled = engine.on_bar(bar)
        assert len(filled) == 1
        assert order.status == OrderStatus.FILLED

    def test_fill_updates_order_details(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order(side=OrderSide.BUY, quantity=100, price=10.0)
        engine.submit_order(order)
        bar = _make_bar(open=9.9, close=10.0, volume=100000)
        engine.on_bar(bar)
        engine.on_bar(bar)
        assert order.filled_qty == 100
        assert order.filled_price > 0
        assert order.commission >= 0

    def test_fill_rejected_by_price_limit(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        order = _make_order(side=OrderSide.BUY, quantity=100, price=10.0)
        engine.submit_order(order)
        bar = _make_bar(open=12.0, close=12.0, volume=100000)  # > 11.0 limit
        filled = engine.on_bar(bar)
        assert len(filled) == 0

    def test_fill_multiple_orders_same_bar(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        o1 = _make_order(ticker="000001.SZ", price=10.0, quantity=100)
        o2 = create_order("000001.SZ", "a_share", "stock", OrderSide.SELL, 50, 10.0)
        engine.submit_order(o1)
        engine.submit_order(o2)
        bar = _make_bar(open=10.0, close=10.0, volume=100000)
        engine.on_bar(bar)
        filled = engine.on_bar(bar)
        assert len(filled) == 2


class TestPaperEngineAccount:
    def test_get_account_returns_dict(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules(), initial_capital=100000.0)
        acct = engine.get_account()
        assert "capital" in acct
        assert "available" in acct
        assert acct["capital"] == 100000.0

    def test_get_positions_returns_dict(self):
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        positions = engine.get_positions()
        assert isinstance(positions, dict)


class TestPaperEngineBrokerAdapterCompliance:
    def test_implements_broker_adapter(self):
        from fisher.broker.adapter import BrokerAdapter
        engine = PaperEngine(A_SHARE_FEE, AShareRules())
        assert isinstance(engine, BrokerAdapter)
