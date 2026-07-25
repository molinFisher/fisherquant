# tests/unit/test_market_akshare.py
import pytest
from fisher.market.akshare import AkshareAdapter
from fisher.config.schemas import MarketConfig


class TestAkshareAdapter:
    def test_source_is_akshare(self):
        gw = AkshareAdapter(MarketConfig(source="akshare"))
        assert gw.source == "akshare"
        assert gw.is_running is False

    @pytest.mark.asyncio
    async def test_run_and_stop(self):
        gw = AkshareAdapter(MarketConfig(source="akshare"))
        await gw.run()
        assert gw.is_running is True
        await gw.stop()
        assert gw.is_running is False

    def test_ticker_normalization(self):
        gw = AkshareAdapter(MarketConfig(source="akshare"))
        assert gw._normalize_ticker("000001", "a_share") == "000001.SZ"
        assert gw._normalize_ticker("600036", "a_share") == "600036.SH"

    @pytest.mark.asyncio
    async def test_subscribe_adds_tickers(self):
        gw = AkshareAdapter(MarketConfig(source="akshare"))
        await gw.subscribe(["000001.SZ", "600036.SH"])
        assert len(gw._subscribed) == 2

    @pytest.mark.asyncio
    async def test_get_bars_returns_dataframe(self):
        gw = AkshareAdapter(MarketConfig(source="akshare"))
        bars = await gw.get_bars("000001.SZ", "2025-07-01", "2025-07-07", "1d")
        assert bars is not None
