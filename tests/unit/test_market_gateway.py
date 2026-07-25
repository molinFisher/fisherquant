# tests/unit/test_market_gateway.py
import pytest
from fisher.market.gateway import MarketGateway, GatewayFactory
from fisher.config.schemas import MarketConfig


class DummyGateway(MarketGateway):
    def __init__(self):
        super().__init__()
        self.tickers = []

    async def _run(self):
        pass

    async def _stop(self):
        pass

    async def subscribe(self, tickers: list[str]):
        self.tickers.extend(tickers)

    async def get_bars(self, ticker: str, start: str, end: str, frequency: str = "1d"):
        return []


class TestMarketGateway:
    @pytest.mark.asyncio
    async def test_run_starts_gateway(self):
        gw = DummyGateway()
        assert gw.is_running is False
        await gw.run()
        assert gw.is_running is True

    @pytest.mark.asyncio
    async def test_stop_stops_gateway(self):
        gw = DummyGateway()
        await gw.run()
        await gw.stop()
        assert gw.is_running is False

    @pytest.mark.asyncio
    async def test_subscribe_stores_tickers(self):
        gw = DummyGateway()
        await gw.subscribe(["000001.SZ", "600036.SH"])
        assert "000001.SZ" in gw.tickers


class TestGatewayFactory:
    def test_default_source(self):
        cfg = MarketConfig(source="akshare")
        assert cfg.source == "akshare"
