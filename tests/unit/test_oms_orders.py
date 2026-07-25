import pytest
from datetime import datetime, timezone
from fisher.oms.orders import Order, create_order

from fisher.event.types import OrderSide, OrderStatus


class TestOrderModel:
    def test_create_order_with_required_fields(self):
        order = create_order(
            ticker="000001.SZ",
            market="a_share",
            asset_type="stock",
            side=OrderSide.BUY,
            quantity=100,
            price=10.0,
        )
        assert order.order_id.startswith("ORD-")
        assert order.ticker == "000001.SZ"
        assert order.market == "a_share"
        assert order.asset_type == "stock"
        assert order.side == OrderSide.BUY
        assert order.quantity == 100
        assert order.price == 10.0
        assert order.filled_qty == 0
        assert order.filled_price == 0.0
        assert order.commission == 0.0
        assert order.status == OrderStatus.NEW
        assert order.order_type == "limit"

    def test_create_order_with_custom_order_type(self):
        order = create_order(
            ticker="000001.SZ",
            market="a_share",
            asset_type="stock",
            side=OrderSide.BUY,
            quantity=100,
            price=10.0,
            order_type="market",
        )
        assert order.order_type == "market"

    def test_order_unique_ids(self):
        o1 = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        o2 = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        assert o1.order_id != o2.order_id

    def test_order_id_increment(self):
        o1 = create_order("A", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        o2 = create_order("B", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        n1 = int(o1.order_id.split("-")[1])
        n2 = int(o2.order_id.split("-")[1])
        assert n2 == n1 + 1

    def test_order_created_at_is_utc(self):
        order = create_order("000001.SZ", "a_share", "stock", OrderSide.BUY, 100, 10.0)
        assert order.created_at.tzinfo is not None
        assert order.created_at.tzinfo == timezone.utc


class TestOrderStatusTransitions:
    def test_new_to_pending_valid(self):
        assert OrderStatus.PENDING in get_valid_transitions(OrderStatus.NEW)

    def test_new_to_submitted_valid(self):
        assert OrderStatus.SUBMITTED in get_valid_transitions(OrderStatus.NEW)

    def test_new_to_rejected_valid(self):
        assert OrderStatus.REJECTED in get_valid_transitions(OrderStatus.NEW)

    def test_new_to_filled_invalid(self):
        assert OrderStatus.FILLED not in get_valid_transitions(OrderStatus.NEW)

    def test_pending_to_submitted_valid(self):
        assert OrderStatus.SUBMITTED in get_valid_transitions(OrderStatus.PENDING)

    def test_pending_to_acked_valid(self):
        assert OrderStatus.ACKED in get_valid_transitions(OrderStatus.PENDING)

    def test_pending_to_rejected_valid(self):
        assert OrderStatus.REJECTED in get_valid_transitions(OrderStatus.PENDING)

    def test_submitted_to_acked_valid(self):
        assert OrderStatus.ACKED in get_valid_transitions(OrderStatus.SUBMITTED)

    def test_submitted_to_partially_filled_valid(self):
        assert OrderStatus.PARTIALLY_FILLED in get_valid_transitions(OrderStatus.SUBMITTED)

    def test_acked_to_partially_filled_valid(self):
        assert OrderStatus.PARTIALLY_FILLED in get_valid_transitions(OrderStatus.ACKED)

    def test_partially_filled_to_filled_valid(self):
        assert OrderStatus.FILLED in get_valid_transitions(OrderStatus.PARTIALLY_FILLED)

    def test_partially_filled_to_partially_filled_valid(self):
        assert OrderStatus.PARTIALLY_FILLED in get_valid_transitions(OrderStatus.PARTIALLY_FILLED)

    def test_filled_terminal_no_transitions(self):
        assert get_valid_transitions(OrderStatus.FILLED) == []

    def test_rejected_terminal_no_transitions(self):
        assert get_valid_transitions(OrderStatus.REJECTED) == []

    def test_cancelled_terminal_no_transitions(self):
        assert get_valid_transitions(OrderStatus.CANCELLED) == []

    def test_any_to_cancelled_except_terminal(self):
        for status in [OrderStatus.NEW, OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.ACKED, OrderStatus.PARTIALLY_FILLED]:
            assert OrderStatus.CANCELLED in get_valid_transitions(status)

    def test_is_terminal(self):
        from fisher.oms.orders import is_terminal_status
        assert is_terminal_status(OrderStatus.FILLED)
        assert is_terminal_status(OrderStatus.REJECTED)
        assert is_terminal_status(OrderStatus.CANCELLED)
        assert not is_terminal_status(OrderStatus.NEW)
        assert not is_terminal_status(OrderStatus.PARTIALLY_FILLED)


def get_valid_transitions(status: OrderStatus) -> list[OrderStatus]:
    from fisher.oms.orders import ORDER_STATUS_TRANSITIONS
    return ORDER_STATUS_TRANSITIONS.get(status, [])
