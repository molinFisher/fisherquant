import pytest
from fisher.event.types import OrderSide
from fisher.oms.orders import Order, create_order
from fisher.position.service import PositionService


def _make_order(ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, price=10.0):
    return create_order(ticker, market, "stock", side, quantity, price)


def _fill_order(order: Order, fill_price: float = 10.0, commission: float = 0.0):
    order.filled_qty = order.quantity
    order.filled_price = fill_price
    order.commission = commission


class TestPositionServiceBasic:
    def test_update_buy_creates_position(self):
        svc = PositionService()
        order = _make_order(quantity=100, price=10.0)
        _fill_order(order, 10.0, 5.0)
        svc.update_on_fill(order, 10.0)
        pos = svc.get_position("000001.SZ")
        assert pos is not None
        assert pos["quantity"] == 100
        assert pos["avg_cost"] > 0

    def test_weighted_average_cost(self):
        svc = PositionService()
        o1 = _make_order(quantity=100, price=10.0)
        _fill_order(o1, 10.0, 5.0)
        svc.update_on_fill(o1, 10.0)

        o2 = _make_order(quantity=100, price=12.0)
        _fill_order(o2, 12.0, 5.0)
        svc.update_on_fill(o2, 12.0)

        pos = svc.get_position("000001.SZ")
        total_cost = (100 * 10.0 + 5.0) + (100 * 12.0 + 5.0)
        expected_avg = total_cost / 200
        assert pos["avg_cost"] == pytest.approx(expected_avg)

    def test_sell_reduces_position(self):
        svc = PositionService()
        o1 = _make_order(quantity=200, price=10.0)
        _fill_order(o1, 10.0, 5.0)
        svc.update_on_fill(o1, 10.0)

        o2 = _make_order(side=OrderSide.SELL, quantity=100, price=11.0)
        _fill_order(o2, 11.0, 5.0)
        svc.update_on_fill(o2, 11.0)

        pos = svc.get_position("000001.SZ")
        assert pos["quantity"] == 100

    def test_sell_to_zero(self):
        svc = PositionService()
        o1 = _make_order(quantity=100, price=10.0)
        _fill_order(o1, 10.0, 5.0)
        svc.update_on_fill(o1, 10.0)

        o2 = _make_order(side=OrderSide.SELL, quantity=100, price=11.0)
        _fill_order(o2, 11.0, 5.0)
        svc.update_on_fill(o2, 11.0)

        pos = svc.get_position("000001.SZ")
        assert pos is None

    def test_get_position_nonexistent(self):
        svc = PositionService()
        assert svc.get_position("NOPE") is None

    def test_get_all_positions(self):
        svc = PositionService()
        o1 = _make_order("A", quantity=100, price=10.0)
        _fill_order(o1)
        svc.update_on_fill(o1, 10.0)

        o2 = _make_order("B", quantity=200, price=20.0)
        _fill_order(o2)
        svc.update_on_fill(o2, 20.0)

        all_pos = svc.get_all_positions()
        assert len(all_pos) == 2

    def test_position_market_value(self):
        svc = PositionService()
        order = _make_order(quantity=100, price=10.0)
        _fill_order(order, 10.0)
        svc.update_on_fill(order, 10.0)

        svc.mark_to_market({"000001.SZ": 11.0})
        pos = svc.get_position("000001.SZ")
        assert pos["market_value"] == pytest.approx(1100.0)
        assert pos["unrealized_pnl"] == pytest.approx(100.0)


class TestPositionServiceTPlus:
    def test_a_share_t1_available_zero_on_fill(self):
        svc = PositionService()
        order = _make_order("000001.SZ", "a_share", OrderSide.BUY, 100, 10.0)
        _fill_order(order, 10.0)
        svc.update_on_fill(order, 10.0)
        pos = svc.get_position("000001.SZ")
        assert pos["available"] == 0  # T+1: not available day of

    def test_a_share_t1_after_settlement(self):
        svc = PositionService()
        order = _make_order("000001.SZ", "a_share", OrderSide.BUY, 100, 10.0)
        _fill_order(order, 10.0)
        svc.update_on_fill(order, 10.0)
        svc.settle_t1()
        pos = svc.get_position("000001.SZ")
        assert pos["available"] == 100

    def test_hk_connect_t0_available_immediately(self):
        svc = PositionService()
        order = _make_order("00700.HK", "hk_connect", OrderSide.BUY, 100, 300.0)
        _fill_order(order, 300.0)
        svc.update_on_fill(order, 300.0)
        pos = svc.get_position("00700.HK")
        assert pos["available"] == 100


class TestPositionServiceFrozen:
    def test_freeze_unfreeze(self):
        svc = PositionService()
        order = _make_order("00700.HK", "hk_connect", OrderSide.BUY, 200, 300.0)
        _fill_order(order, 300.0)
        svc.update_on_fill(order, 300.0)
        svc.freeze("00700.HK", 50)
        pos = svc.get_position("00700.HK")
        assert pos["frozen"] == 50
        assert pos["available"] == 150

    def test_freeze_exceeds_available_raises(self):
        svc = PositionService()
        order = _make_order("00700.HK", "hk_connect", OrderSide.BUY, 100, 300.0)
        _fill_order(order, 300.0)
        svc.update_on_fill(order, 300.0)
        with pytest.raises(ValueError, match="freeze"):
            svc.freeze("00700.HK", 200)

    def test_unfreeze(self):
        svc = PositionService()
        order = _make_order("00700.HK", "hk_connect", OrderSide.BUY, 200, 300.0)
        _fill_order(order, 300.0)
        svc.update_on_fill(order, 300.0)
        svc.freeze("00700.HK", 50)
        svc.unfreeze("00700.HK", 20)
        pos = svc.get_position("00700.HK")
        assert pos["frozen"] == 30
        assert pos["available"] == 170


class TestPositionServiceCurrency:
    def test_hkd_to_cny_conversion(self):
        svc = PositionService(hkd_cny_rate=0.92)
        order = _make_order("00700.HK", "hk_connect", OrderSide.BUY, 100, 300.0)
        _fill_order(order, 300.0)
        svc.update_on_fill(order, 300.0)
        pos = svc.get_position("00700.HK")
        assert pos["cost_cny"] == pytest.approx(300.0 * 100 * 0.92)

    def test_a_share_no_conversion_needed(self):
        svc = PositionService(hkd_cny_rate=0.92)
        order = _make_order("000001.SZ", "a_share", OrderSide.BUY, 100, 10.0)
        _fill_order(order, 10.0)
        svc.update_on_fill(order, 10.0)
        pos = svc.get_position("000001.SZ")
        assert "cost_cny" in pos
        assert pos["cost_cny"] == pytest.approx(pos["avg_cost"] * pos["quantity"])


class TestPositionServiceSnapshot:
    def test_snapshot_to_dict(self):
        svc = PositionService()
        order = _make_order(quantity=100, price=10.0)
        _fill_order(order, 10.0)
        svc.update_on_fill(order, 10.0)
        snap = svc.snapshot()
        assert isinstance(snap, list)
        assert len(snap) == 1
        assert snap[0]["ticker"] == "000001.SZ"
