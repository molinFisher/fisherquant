# fisher/market/gateway.py
from abc import ABC, abstractmethod
from ..config.schemas import MarketConfig


class MarketGateway(ABC):
    def __init__(self):
        self._running = False
        self.source: str = ""

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self):
        self._running = True
        await self._run()

    async def stop(self):
        self._running = False
        await self._stop()

    @abstractmethod
    async def _run(self): ...

    @abstractmethod
    async def _stop(self): ...

    @abstractmethod
    async def subscribe(self, tickers: list[str]): ...

    @abstractmethod
    async def get_bars(self, ticker: str, start: str, end: str, frequency: str = "1d"): ...


class GatewayFactory:
    @staticmethod
    def create(cfg: MarketConfig) -> MarketGateway:
        if cfg.source == "akshare":
            from .akshare import AkshareAdapter
            return AkshareAdapter(cfg)
        raise ValueError(f"Unknown market source: {cfg.source}")
