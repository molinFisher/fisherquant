# fisher/market/model.py
"""Core market data models (plain dataclasses).

These model classes represent raw market data structures used by the
gateway layer. For event-system versions of Bar and MarketSnapshot,
see fisher.event.types which extend the base Event dataclass.
"""
from dataclasses import dataclass
from enum import Enum


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CONVERTIBLE_BOND = "convertible_bond"


@dataclass
class Bar:
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    market: str = "a_share"
    frequency: str = "1d"
    trade_date: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "market": self.market,
            "trade_date": self.trade_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
        }


@dataclass
class Quote:
    ticker: str
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    bid_volume: int = 0
    ask_volume: int = 0
    timestamp: float = 0.0

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 4)


@dataclass
class MarketSnapshot:
    ticker: str
    market: str = "a_share"
    asset_type: AssetType = AssetType.STOCK
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    pre_close: float = 0.0
    volume: int = 0
    amount: float = 0.0
    timestamp: float = 0.0

    @property
    def change_pct(self) -> float:
        if self.pre_close == 0:
            return 0.0
        return round((self.last_price - self.pre_close) / self.pre_close, 6)
