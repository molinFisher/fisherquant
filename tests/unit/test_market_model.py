import pytest
from fisher.market.model import Bar, Quote, MarketSnapshot, AssetType


class TestBar:
    def test_bar_creation(self):
        b = Bar(
            ticker="000001.SZ",
            market="a_share",
            frequency="1d",
            open=10.0,
            high=11.0,
            low=9.8,
            close=10.5,
            volume=1000000,
            amount=10500000.0,
            trade_date="2025-01-02",
        )
        assert b.ticker == "000001.SZ"
        assert b.market == "a_share"
        assert b.close == 10.5
        assert b.trade_date == "2025-01-02"

    def test_bar_defaults(self):
        b = Bar(ticker="000001.SZ", open=0, high=0, low=0, close=0, volume=0, amount=0)
        assert b.frequency == "1d"
        assert b.market == "a_share"

    def test_bar_to_dict(self):
        b = Bar(ticker="000001.SZ", open=10.0, high=11.0, low=9.8, close=10.5, volume=1000000, amount=10500000.0, trade_date="2025-01-02")
        d = b.to_dict()
        assert d["ticker"] == "000001.SZ"
        assert d["close"] == 10.5


class TestQuote:
    def test_quote_creation(self):
        q = Quote(
            ticker="000001.SZ",
            last_price=10.5,
            bid=10.49,
            ask=10.51,
            bid_volume=5000,
            ask_volume=3000,
        )
        assert q.last_price == 10.5
        assert q.bid == 10.49
        assert q.spread == 0.02

    def test_quote_defaults(self):
        q = Quote(ticker="000001.SZ")
        assert q.last_price == 0.0
        assert q.bid == 0.0


class TestMarketSnapshot:
    def test_snapshot_creation(self):
        s = MarketSnapshot(
            ticker="000001.SZ",
            market="a_share",
            last_price=10.5,
            open=10.0,
            high=11.0,
            low=9.8,
            pre_close=10.2,
            volume=1000000,
            amount=10500000.0,
        )
        assert s.change_pct == pytest.approx(0.0294, abs=0.001)
        assert s.ticker == "000001.SZ"
