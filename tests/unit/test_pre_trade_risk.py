"""G3 事前风控补全单测：单笔量/名义/单标的持仓/杠杆/挂单上限。"""
from fisher.oms.orders import create_order
from fisher.risk.pre_trade import (
    MaxOrderQtyRule,
    MaxNotionalRule,
    MaxPositionPerSymbolRule,
    MaxLeverageRule,
    MaxOpenOrdersRule,
)
from fisher.event.types import OrderSide


class _FakePos:
    def __init__(self, positions: dict):
        self._p = positions

    def get_position(self, ticker):
        return self._p.get(ticker)

    def get_all_positions(self):
        return self._p


def _buy(qty=100, price=10.0, ticker="600519.SH"):
    return create_order(ticker, "a_share", "stock", OrderSide.BUY, qty, price)


def test_max_order_qty_boundary():
    r = MaxOrderQtyRule(max_qty=1000)
    assert r.check(_buy(qty=1000))[0] is True
    assert r.check(_buy(qty=1001))[0] is False


def test_max_notional_uses_market_price():
    r = MaxNotionalRule(max_notional=1_000_000.0)
    # 仅用 order.price=10 * 100000 = 1_000_000 恰好不越界
    assert r.check(_buy(qty=100000, price=10.0))[0] is True
    # order.price=10 * 100001 = 1_000_010 > 1_000_000
    assert r.check(_buy(qty=100001, price=10.0))[0] is False
    # 市价 12 * 100000 = 1_200_000 > 1_000_000
    assert r.check(_buy(qty=100000, price=10.0), capital=1e6, market_price=12.0)[0] is False


def test_max_position_per_symbol_with_existing():
    pos = _FakePos({"600519.SH": {"quantity": 100, "avg_cost": 10.0, "market_value": 1000.0}})
    r = MaxPositionPerSymbolRule(max_value=2000.0)
    # 现有 1000 + 新 10*100=1000 = 2000 恰好不越界
    assert r.check(_buy(qty=100, price=10.0), pos_svc=pos)[0] is True
    # 现有 1000 + 新 10*101=1010 = 2010 > 2000
    assert r.check(_buy(qty=101, price=10.0), pos_svc=pos)[0] is False


def test_max_leverage_with_existing_exposure():
    pos = _FakePos({
        "600519.SH": {"quantity": 100, "market_value": 600_000.0},
        "000001.SZ": {"quantity": 200, "market_value": 300_000.0},
    })
    r = MaxLeverageRule(max_leverage=1.0)
    # 现有敞口 900_000；新单 10*1000=10_000；总 910_000 / 1e6 = 0.91 <= 1.0
    assert r.check(_buy(qty=1000, price=10.0), pos_svc=pos, capital=1_000_000.0)[0] is True
    # 新单 10*20000=200_000；总 1_100_000 / 1e6 = 1.1 > 1.0
    assert r.check(_buy(qty=20000, price=10.0), pos_svc=pos, capital=1_000_000.0)[0] is False


def test_max_leverage_zero_capital_passes():
    r = MaxLeverageRule(max_leverage=1.0)
    assert r.check(_buy(qty=100, price=10.0), capital=0.0)[0] is True


def test_max_open_orders_via_provider():
    counter = {"n": 49}
    r = MaxOpenOrdersRule(max_open=50, open_orders_provider=lambda: counter["n"])
    assert r.check(_buy())[0] is True
    counter["n"] = 50
    ok, reason = r.check(_buy())
    assert ok is False and "MaxOpenOrders" in reason
