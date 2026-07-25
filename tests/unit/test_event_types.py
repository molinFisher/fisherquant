import time
from fisher.event.types import (
    Bar, Signal, OrderPending, OrderFilled, PositionUpdate,
    RiskAlert, MarketOpen, DividendEvent, Event, OrderSide, OrderStatus,
)


class TestEvent:
    def test_event_has_timestamp(self):
        e = Event()
        assert isinstance(e.timestamp, float)
        assert e.timestamp > 0

    def test_event_has_type_attr(self):
        e = MarketOpen(timestamp=1.0)
        assert e.__event_type__ == "market_open"


class TestBar:
    def test_bar_fields(self):
        b = Bar(
            ticker="000001.SZ", market="a_share", frequency="1d",
            open=10.0, high=11.0, low=9.5, close=10.5,
            volume=1000000, amount=10500000.0, bar_time=0.0,
        )
        assert b.ticker == "000001.SZ"
        assert b.market == "a_share"
        assert b.close == 10.5

    def test_bar_default_frequency(self):
        b = Bar(ticker="000001.SZ", open=10.0, high=11.0, low=9.5, close=10.5, volume=0, amount=0)
        assert b.frequency == "1d"


class TestSignal:
    def test_signal_fields(self):
        s = Signal(
            strategy="trend_following", ticker="000001.SZ",
            market="a_share", side=OrderSide.BUY,
            quantity=100, limit_price=10.5, confidence=0.8,
            reason="ma_crossover",
        )
        assert s.side == OrderSide.BUY
        assert s.confidence == 0.8

    def test_signal_has_event_type(self):
        s = Signal(strategy="x", ticker="x", market="a_share", side=OrderSide.BUY, quantity=0, confidence=0)
        assert s.__event_type__ == "signal"


class TestOrderPending:
    def test_order_pending_has_order_id(self):
        o = OrderPending(
            ticker="000001.SZ", market="a_share", side=OrderSide.BUY,
            quantity=100, price=10.0, order_type="limit",
            status=OrderStatus.PENDING,
        )
        assert o.status == OrderStatus.PENDING


class TestOrderFilled:
    def test_filled_has_price_qty(self):
        o = OrderFilled(
            order_id="oid-1", ticker="000001.SZ", filled_qty=100,
            filled_price=10.2, commission=2.5, timestamp=0.0,
        )
        assert o.filled_qty == 100
        assert o.commission == 2.5


class TestPositionUpdate:
    def test_fields(self):
        p = PositionUpdate(
            ticker="000001.SZ", market="a_share", asset_type="stock",
            quantity=500, avg_cost=10.0, market_value=5100.0,
            unrealized_pnl=100.0, available=400,
        )
        assert p.market_value == 5100.0


class TestRiskAlert:
    def test_fields(self):
        r = RiskAlert(
            rule="DailyLossLimit", ticker=None,
            severity="ERROR", message="Daily loss 5.2% exceeded 5% limit",
        )
        assert r.severity == "ERROR"


class TestDividendEvent:
    def test_fields(self):
        d = DividendEvent(
            ticker="000001.SZ", ex_date="2025-06-15",
            cash_per_share=0.5, bonus_ratio=0.0,
        )
        assert d.cash_per_share == 0.5
