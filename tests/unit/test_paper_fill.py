import pytest
from fisher.event.types import Bar, OrderSide, OrderStatus
from fisher.oms.orders import Order, create_order
from fisher.paper.fill import FillSimulator


def _make_order(ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, price=10.0):
    return create_order(ticker, market, "stock", side, quantity, price)


def _make_bar(
    ticker="000001.SZ", market="a_share", open=10.0, high=10.5, low=9.5, close=10.2,
    volume=100000, amount=1000000.0, frequency="1d",
):
    return Bar(
        ticker=ticker, market=market, frequency=frequency,
        open=open, high=high, low=low, close=close,
        volume=volume, amount=amount, bar_time=1234567890.0,
    )


class TestFillSimulatorPriceLimits:
    def test_buy_within_price_limit_fills(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=0.10)
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=9.8, close=9.9)
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is True
        assert fill_price == 9.9

    def test_buy_below_limit_price_fills(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=0.10)
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=9.0, close=9.5)
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is True

    def test_buy_above_price_limit_rejects(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=0.10)
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=12.0, close=11.5)  # > 10 * 1.10 = 11.0
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is False

    def test_sell_within_price_limit_fills(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=0.10)
        order = _make_order(price=10.0, side=OrderSide.SELL)
        bar = _make_bar(open=10.2, close=10.1)
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is True

    def test_sell_below_limit_rejects(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=0.10)
        order = _make_order(price=10.0, side=OrderSide.SELL)
        bar = _make_bar(open=8.0, close=8.5)  # < 10 * 0.90 = 9.0
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is False

    def test_hk_no_price_limits(self):
        sim = FillSimulator(fill_price_mode="current_close", price_limit_ratio=None)
        order = _make_order(ticker="00700.HK", market="hk_connect", price=300.0, side=OrderSide.BUY)
        bar = _make_bar(ticker="00700.HK", market="hk_connect", open=500.0, close=500.0)
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is True


class TestFillSimulatorFillModes:
    def test_mode_next_open(self):
        sim = FillSimulator(fill_price_mode="next_open")
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=9.8, close=10.2)
        filled, fill_price = sim.check_fill(order, bar)
        assert filled is True
        assert fill_price == 9.8

    def test_mode_current_close(self):
        sim = FillSimulator(fill_price_mode="current_close")
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=9.8, close=10.2)
        filled, fill_price = sim.check_fill(order, bar)
        assert fill_price == 10.2

    def test_mode_vwap(self):
        sim = FillSimulator(fill_price_mode="vwap")
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=10.0, high=10.4, low=9.6, close=10.2, amount=1_000_000.0, volume=100_000)
        filled, fill_price = sim.check_fill(order, bar)
        expected_vwap = 1_000_000.0 / 100_000  # 10.0
        assert fill_price == pytest.approx(expected_vwap)

    def test_mode_ohlc4(self):
        sim = FillSimulator(fill_price_mode="ohlc4")
        order = _make_order(price=10.0, side=OrderSide.BUY)
        bar = _make_bar(open=9.8, high=10.2, low=9.6, close=10.0)
        filled, fill_price = sim.check_fill(order, bar)
        expected = (9.8 + 10.2 + 9.6 + 10.0) / 4
        assert fill_price == pytest.approx(expected)

    def test_default_mode_is_current_close(self):
        sim = FillSimulator()
        assert sim._mode == "current_close"


class TestFillSimulatorVolume:
    def test_sufficient_volume_fills(self):
        sim = FillSimulator(fill_price_mode="current_close")
        order = _make_order(quantity=500)
        bar = _make_bar(volume=100000)
        filled, _ = sim.check_fill(order, bar)
        assert filled is True

    def test_zero_volume_rejects(self):
        sim = FillSimulator(fill_price_mode="current_close")
        order = _make_order(quantity=100)
        bar = _make_bar(volume=0)
        filled, _ = sim.check_fill(order, bar)
        assert filled is False

    def test_insufficient_volume_configurable(self):
        sim = FillSimulator(fill_price_mode="current_close", min_volume_ratio=0.5)
        bar = _make_bar(volume=50)
        order = _make_order(quantity=100)
        filled, _ = sim.check_fill(order, bar)
        assert filled is False

    def test_min_volume_enough(self):
        sim = FillSimulator(fill_price_mode="current_close", min_volume_ratio=0.5)
        bar = _make_bar(volume=60)
        order = _make_order(quantity=30)
        filled, _ = sim.check_fill(order, bar)
        assert filled is True


class TestFillSimulatorWrongTicker:
    def test_wrong_ticker_no_fill(self):
        sim = FillSimulator(fill_price_mode="current_close")
        order = _make_order(ticker="000001.SZ", price=10.0)
        bar = _make_bar(ticker="000002.SZ")
        filled, _ = sim.check_fill(order, bar)
        assert filled is False
