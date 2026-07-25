import pytest
from fisher.oms.engine import OMSEngine
from fisher.oms.orders import Order, create_order
from fisher.event.types import OrderSide, OrderStatus


def _make_buy(ticker="000001.SZ", quantity=100, price=10.0):
    return create_order(ticker, "a_share", "stock", OrderSide.BUY, quantity, price)


def _make_sell(ticker="000001.SZ", quantity=100, price=10.0):
    return create_order(ticker, "a_share", "stock", OrderSide.SELL, quantity, price)


def _make_condition(ticker="000001.SZ", quantity=100, price=10.0, cond_price=9.0, cond_type="stop_loss"):
    return create_order(
        ticker, "a_share", "stock", OrderSide.SELL, quantity, price,
        condition_price=cond_price, condition_type=cond_type,
    )


class TestOMSEngineSubmit:
    def test_submit_adds_order(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        assert engine.get_order(order.order_id) is order

    def test_submit_transitions_new_to_pending(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        assert order.status == OrderStatus.PENDING

    def test_submit_rejects_invalid_transition(self):
        engine = OMSEngine()
        order = _make_buy()
        order.status = OrderStatus.FILLED
        with pytest.raises(ValueError, match="Cannot transition"):
            engine.submit(order)

    def test_submit_condition_order_goes_to_queue(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=9.0, cond_type="stop_loss")
        engine.submit(order)
        assert len(engine._condition_queue) == 1
        assert order.status == OrderStatus.NEW  # stays new until triggered

    def test_multiple_orders(self):
        engine = OMSEngine()
        o1 = _make_buy("A")
        o2 = _make_buy("B")
        engine.submit(o1)
        engine.submit(o2)
        assert len(engine.get_pending()) == 2


class TestOMSEngineCancel:
    def test_cancel_moves_to_cancelled(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        engine.cancel(order.order_id)
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_nonexistent_raises(self):
        engine = OMSEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.cancel("NONEXISTENT")

    def test_cancel_terminal_raises(self):
        engine = OMSEngine()
        order = _make_buy()
        order.status = OrderStatus.FILLED
        engine._orders[order.order_id] = order
        with pytest.raises(ValueError, match="Cannot transition"):
            engine.cancel(order.order_id)

    def test_cancel_removes_from_pending(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        engine.cancel(order.order_id)
        assert engine.get_order(order.order_id).status == OrderStatus.CANCELLED
        assert len(engine.get_pending()) == 0


class TestOMSEngineUpdateStatus:
    def test_update_status_valid_transition(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        engine.update_status(order.order_id, OrderStatus.SUBMITTED)
        assert order.status == OrderStatus.SUBMITTED

    def test_update_status_invalid_raises(self):
        engine = OMSEngine()
        order = _make_buy()
        engine.submit(order)
        with pytest.raises(ValueError, match="Cannot transition"):
            engine.update_status(order.order_id, OrderStatus.FILLED)

    def test_update_fill_partial(self):
        engine = OMSEngine()
        order = _make_buy(quantity=200)
        engine.submit(order)
        engine.update_status(order.order_id, OrderStatus.SUBMITTED)
        engine.update_fill(order.order_id, filled_qty=100, filled_price=10.5, commission=2.5)
        assert order.filled_qty == 100
        assert order.filled_price == 10.5
        assert order.commission == 2.5
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_update_fill_complete(self):
        engine = OMSEngine()
        order = _make_buy(quantity=100)
        engine.submit(order)
        engine.update_status(order.order_id, OrderStatus.SUBMITTED)
        engine.update_fill(order.order_id, filled_qty=100, filled_price=10.5, commission=4.0)
        assert order.filled_qty == 100
        assert order.status == OrderStatus.FILLED

    def test_update_fill_overfill_raises(self):
        engine = OMSEngine()
        order = _make_buy(quantity=100)
        engine.submit(order)
        engine.update_status(order.order_id, OrderStatus.SUBMITTED)
        with pytest.raises(ValueError, match="filled quantity"):
            engine.update_fill(order.order_id, filled_qty=200, filled_price=10.5, commission=4.0)

    def test_update_fill_nonexistent_raises(self):
        engine = OMSEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.update_fill("NOTHERE", filled_qty=50, filled_price=10.0, commission=1.0)


class TestOMSEngineConditionQueue:
    def test_check_conditions_triggers_stop_loss(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=9.0, cond_type="stop_loss", price=10.0)
        engine.submit(order)
        triggered = engine.check_conditions(ticker="000001.SZ", current_price=8.5)
        assert len(triggered) == 1
        assert triggered[0].order_id == order.order_id

    def test_stop_loss_not_triggered_above(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=9.0, cond_type="stop_loss", price=10.0)
        engine.submit(order)
        triggered = engine.check_conditions(ticker="000001.SZ", current_price=9.5)
        assert len(triggered) == 0

    def test_take_profit_triggers_above(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=11.0, cond_type="take_profit", price=10.0)
        engine.submit(order)
        triggered = engine.check_conditions(ticker="000001.SZ", current_price=11.5)
        assert len(triggered) == 1

    def test_take_profit_not_triggered_below(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=11.0, cond_type="take_profit", price=10.0)
        engine.submit(order)
        triggered = engine.check_conditions(ticker="000001.SZ", current_price=10.5)
        assert len(triggered) == 0

    def test_condition_wrong_ticker_ignored(self):
        engine = OMSEngine()
        order = _make_condition(cond_price=9.0, cond_type="stop_loss", price=10.0)
        engine.submit(order)
        triggered = engine.check_conditions(ticker="OTHER", current_price=8.5)
        assert len(triggered) == 0


class TestOMSEngineGetOrders:
    def test_get_pending_returns_active_only(self):
        engine = OMSEngine()
        o1 = _make_buy("A")
        o2 = _make_buy("B")
        engine.submit(o1)
        engine.submit(o2)
        engine.cancel(o2.order_id)
        pending = engine.get_pending()
        assert len(pending) == 1
        assert pending[0].order_id == o1.order_id

    def test_get_order_returns_none_for_missing(self):
        engine = OMSEngine()
        assert engine.get_order("NOPE") is None

    def test_get_all_orders(self):
        engine = OMSEngine()
        o1 = _make_buy("A")
        o2 = _make_buy("B")
        engine.submit(o1)
        engine.submit(o2)
        engine.cancel(o2.order_id)
        assert len(engine.get_all_orders()) == 2
