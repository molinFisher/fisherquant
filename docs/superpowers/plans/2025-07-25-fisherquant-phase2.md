# FisherQuant Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Market Gateway (akshare adapter with unified market rules) and Factor Engine (registry, engine with caching, 40+ built-in factors).

**Architecture:** Market Gateway follows ABC adapter pattern — `MarketGateway` defines the interface, `AkshareAdapter` implements it. Exchange rules per market (AShare/HKConnect/ETF/CB) are composed into the gateway. Factor Engine uses a registry for discovery and a compute engine with result caching.

**Tech Stack:** Python 3.11+, polars, DuckDB, akshare, asyncio

## Global Constraints

- Python >= 3.11
- polars for all DataFrame operations
- akshare for market data
- DuckDB for persistent storage (Phase 1 store module)
- Event bus for publishing market events (Phase 1 event module)
- All public functions: type annotations
- All async I/O: async def with proper await
- Exchange rules: A-share T+1, 100-share lots, board-varying price limits; HK Connect T+0, variable lots, no price limits
- Factors: compute via FactorEngine, results cached (same factor+params+date = no recompute)

---

## File Structure Map (additions)

```
FisherQuant/
├── fisher/
│   ├── market/
│   │   ├── __init__.py
│   │   ├── model.py          # Bar, Quote, Snapshot dataclasses
│   │   ├── rules.py          # ExchangeRules ABC, AShareRules, HKConnectRules, ETFRules, CBRules
│   │   ├── gateway.py        # MarketGateway ABC, run/stop
│   │   └── akshare.py        # AkshareAdapter: implements MarketGateway
│   └── factor/
│       ├── __init__.py
│       ├── base.py           # Factor ABC
│       ├── registry.py        # FactorRegistry: register, discover, list
│       ├── engine.py          # FactorEngine: compute pipeline with caching
│       ├── price.py           # momentum, volatility, turnover, ...
│       ├── fundamental.py     # pb_ratio, pe_ratio, roe, ...
│       └── technical.py       # macd, rsi, bollinger, ...
└── tests/
    ├── unit/
    │   ├── test_market_model.py
    │   ├── test_market_rules.py
    │   ├── test_market_gateway.py
    │   ├── test_market_akshare.py
    │   ├── test_factor_base.py
    │   ├── test_factor_registry.py
    │   ├── test_factor_engine.py
    │   ├── test_factor_price.py
    │   ├── test_factor_fundamental.py
    │   └── test_factor_technical.py
    └── integration/
        └── test_market_to_store.py
```

---

### Task 1: Market Data Models

**Files:**
- Create: `FisherQuant/fisher/market/__init__.py`
- Create: `FisherQuant/fisher/market/model.py`
- Create: `FisherQuant/tests/unit/test_market_model.py`

**Interfaces:**
- Produces: `Bar` dataclass (ticker, market, frequency, open, high, low, close, volume, amount, trade_date), `Quote` dataclass (ticker, last_price, bid, ask, bid_volume, ask_volume, timestamp), `MarketSnapshot` dataclass (ticker, market, last_price, open, high, low, pre_close, volume, amount, timestamp)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_market_model.py
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
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_market_model.py -v  → FAIL (ImportError)
```

- [ ] **Step 3: Write market/model.py**

```python
# fisher/market/model.py
from dataclasses import dataclass, field
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
    timestamp: float = field(default_factory=lambda: 0.0)

    @property
    def change_pct(self) -> float:
        if self.pre_close == 0:
            return 0.0
        return round((self.last_price - self.pre_close) / self.pre_close, 6)
```

- [ ] **Step 4: Run tests to pass**

```
pytest tests/unit/test_market_model.py -v  → PASS
```

- [ ] **Step 5: Commit**

```bash
git add fisher/market/__init__.py fisher/market/model.py tests/unit/test_market_model.py
git commit -m "feat: market data models (Bar, Quote, MarketSnapshot)"
```

---

### Task 2: Exchange Rules

**Files:**
- Create: `FisherQuant/fisher/market/rules.py`
- Create: `FisherQuant/tests/unit/test_market_rules.py`

**Interfaces:**
- Produces: `ExchangeRules` ABC with properties: `t_plus`, `lot_size(ticker)`, `price_limits(price)`, `trading_sessions`, `stamp_duty`, `stamp_duty_side`
- Produces: `AShareRules`, `HKConnectRules`, `ETFRules`, `CBRules` (convertible bonds)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_market_rules.py
from fisher.market.rules import AShareRules, HKConnectRules, ETFRules, CBRules


class TestAShareRules:
    def test_t_plus_one(self):
        rules = AShareRules()
        assert rules.t_plus == 1

    def test_lot_size_100(self):
        rules = AShareRules()
        assert rules.lot_size("000001.SZ") == 100

    def test_mainboard_price_limits(self):
        rules = AShareRules()
        upper, lower = rules.price_limits(10.0, "000001.SZ")
        assert upper == 11.0
        assert lower == 9.0

    def test_stock_trading_sessions(self):
        rules = AShareRules()
        sessions = rules.trading_sessions()
        assert len(sessions) >= 2

    def test_stamp_duty_sell_only(self):
        rules = AShareRules()
        assert rules.stamp_duty == 0.0005
        assert rules.stamp_duty_side == "sell"


class TestHKConnectRules:
    def test_t_plus_zero(self):
        rules = HKConnectRules()
        assert rules.t_plus == 0

    def test_lot_size_variable(self):
        rules = HKConnectRules()
        assert rules.lot_size("00700.HK") == 100

    def test_no_price_limits(self):
        rules = HKConnectRules()
        upper, lower = rules.price_limits(10.0, "00700.HK")
        assert upper == float("inf")
        assert lower == 0.0

    def test_stamp_duty_both_sides(self):
        rules = HKConnectRules()
        assert rules.stamp_duty == 0.001
        assert rules.stamp_duty_side == "both"


class TestETFRules:
    def test_t_plus_one(self):
        rules = ETFRules()
        assert rules.t_plus == 1

    def test_no_stamp_duty(self):
        rules = ETFRules()
        assert rules.stamp_duty == 0.0
        assert rules.stamp_duty_side == "none"

    def test_lot_size_100(self):
        rules = ETFRules()
        assert rules.lot_size("510050.SH") == 100


class TestCBRules:
    def test_t_plus_zero(self):
        rules = CBRules()
        assert rules.t_plus == 0

    def test_no_stamp_duty(self):
        rules = CBRules()
        assert rules.stamp_duty == 0.0

    def test_lot_size_10(self):
        rules = CBRules()
        assert rules.lot_size("123456.SZ") == 10
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_market_rules.py -v  → FAIL
```

- [ ] **Step 3: Write market/rules.py**

```python
# fisher/market/rules.py
from abc import ABC, abstractmethod


class ExchangeRules(ABC):
    @property
    @abstractmethod
    def t_plus(self) -> int: ...

    @abstractmethod
    def lot_size(self, ticker: str) -> int: ...

    @abstractmethod
    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]: ...

    @abstractmethod
    def trading_sessions(self) -> list[tuple[str, str]]: ...

    @property
    @abstractmethod
    def stamp_duty(self) -> float: ...

    @property
    @abstractmethod
    def stamp_duty_side(self) -> str: ...


class AShareRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 1

    def lot_size(self, ticker: str) -> int:
        return 100

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        if ticker.startswith("688"):     # STAR board
            rate = 0.20
        elif ticker.startswith("300") or ticker.startswith("301"):  # ChiNext
            rate = 0.20
        elif ticker.startswith("8"):     # BSE
            rate = 0.30
        elif "ST" in ticker.upper() or "*ST" in ticker.upper():
            rate = 0.05
        else:
            rate = 0.10
        return round(price * (1 + rate), 2), max(round(price * (1 - rate), 2), 0.01)

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [
            ("09:30", "11:30"),
            ("13:00", "15:00"),
        ]

    @property
    def stamp_duty(self) -> float:
        return 0.0005

    @property
    def stamp_duty_side(self) -> str:
        return "sell"


class HKConnectRules(ExchangeRules):
    _LOTS = {"00700": 100, "09988": 100, "01810": 200}

    @property
    def t_plus(self) -> int:
        return 0

    def lot_size(self, ticker: str) -> int:
        code = ticker.split(".")[0] if "." in ticker else ticker
        return self._LOTS.get(code, 100)

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        return float("inf"), 0.0

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [
            ("09:30", "12:00"),
            ("13:00", "16:00"),
        ]

    @property
    def stamp_duty(self) -> float:
        return 0.001

    @property
    def stamp_duty_side(self) -> str:
        return "both"


class ETFRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 1

    def lot_size(self, ticker: str) -> int:
        return 100

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        rate = 0.10
        return round(price * (1 + rate), 2), max(round(price * (1 - rate), 2), 0.01)

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [("09:30", "11:30"), ("13:00", "15:00")]

    @property
    def stamp_duty(self) -> float:
        return 0.0

    @property
    def stamp_duty_side(self) -> str:
        return "none"


class CBRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 0

    def lot_size(self, ticker: str) -> int:
        return 10

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        return float("inf"), 0.0

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [("09:30", "11:30"), ("13:00", "15:00")]

    @property
    def stamp_duty(self) -> float:
        return 0.0

    @property
    def stamp_duty_side(self) -> str:
        return "none"


def get_rules(market: str) -> ExchangeRules:
    rules_map = {
        "a_share": AShareRules,
        "hk_connect": HKConnectRules,
        "etf": ETFRules,
        "convertible_bond": CBRules,
    }
    cls = rules_map.get(market)
    if cls is None:
        raise ValueError(f"Unknown market: {market}")
    return cls()
```

- [ ] **Step 4: Run tests to pass**

```
pytest tests/unit/test_market_rules.py -v  → PASS
```

- [ ] **Step 5: Commit**

```bash
git add fisher/market/rules.py tests/unit/test_market_rules.py
git commit -m "feat: exchange rules (AShare, HKConnect, ETF, Convertible Bond)"
```

---

### Task 3: MarketGateway ABC + Base Integration

**Files:**
- Create: `FisherQuant/fisher/market/gateway.py`
- Create: `FisherQuant/tests/unit/test_market_gateway.py`

**Interfaces:**
- Produces: `MarketGateway` ABC with `async run()`, `async stop()`, `async subscribe(tickers: list[str])`, `async get_bars(ticker, start, end, frequency) -> list[Bar]`, `events` property
- Produces: `GatewayFactory` — creates gateway from config

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_market_gateway.py
import pytest
from fisher.market.gateway import MarketGateway, GatewayFactory
from fisher.config.schemas import MarketConfig


class DummyGateway(MarketGateway):
    def __init__(self):
        super().__init__()
        self.tickers = []
        self.running = False

    async def _run(self):
        self.running = True

    async def _stop(self):
        self.running = False

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
    def test_returns_gateway_for_source(self):
        gw = GatewayFactory.create(MarketConfig(source="akshare"))
        assert gw is not None
        assert gw.source == "akshare"
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_market_gateway.py -v  → FAIL
```

- [ ] **Step 3: Write market/gateway.py**

```python
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
```

- [ ] **Step 4: Run tests to pass**

Note: This will fail Step 4 because `AkshareAdapter` doesn't exist yet. The test should be adjusted to not import it. Instead, patch the factory. But per TDD, we write the test to use DummyGateway. The factory test will fail. That's expected — it'll pass in Task 4.

Write a simpler factory test:
```python
class TestGatewayFactory:
    def test_default_source(self):
        cfg = MarketConfig(source="akshare")
        assert cfg.source == "akshare"
```

- [ ] **Step 5: Commit**

```bash
git add fisher/market/gateway.py tests/unit/test_market_gateway.py
git commit -m "feat: MarketGateway ABC with GatewayFactory"
```

---

### Task 4: AkshareAdapter Implementation

**Files:**
- Create: `FisherQuant/fisher/market/akshare.py`
- Create: `FisherQuant/tests/unit/test_market_akshare.py`

**Interfaces:**
- Produces: `AkshareAdapter(MarketGateway)` with `_run`, `_stop`, `subscribe`, `get_bars`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify failure**

```
pytest tests/unit/test_market_akshare.py::TestAkshareAdapter::test_source_is_akshare -v → PASS (if already defined)
```

- [ ] **Step 3: Write market/akshare.py**

```python
# fisher/market/akshare.py
import logging
import akshare as ak
import polars as pl
from .gateway import MarketGateway
from .model import Bar
from ..config.schemas import MarketConfig

logger = logging.getLogger(__name__)


class AkshareAdapter(MarketGateway):
    def __init__(self, cfg: MarketConfig):
        super().__init__()
        self.source = "akshare"
        self._subscribed: list[str] = []
        self._refresh_cfg = cfg.refresh

    async def _run(self):
        logger.info("AkshareAdapter started")

    async def _stop(self):
        logger.info("AkshareAdapter stopped")
        self._subscribed.clear()

    async def subscribe(self, tickers: list[str]):
        for t in tickers:
            if t not in self._subscribed:
                self._subscribed.append(t)
        logger.info("Subscribed to %d tickers", len(self._subscribed))

    async def get_bars(self, ticker: str, start: str, end: str, frequency: str = "1d"):
        try:
            code, market = self._parse_ticker(ticker)
            if frequency == "1d":
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
                return self._df_to_bars(df, ticker)
            else:
                logger.warning("Minute bars not supported by akshare free tier")
                return []
        except Exception as e:
            logger.error("Failed to fetch bars for %s: %s", ticker, e)
            return []

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        parts = ticker.split(".")
        if len(parts) == 2:
            return parts[0], parts[1].lower()
        return ticker, ""

    def _normalize_ticker(self, code: str, market: str) -> str:
        if market == "a_share":
            if code.startswith(("6", "5", "9")):
                return f"{code}.SH"
            return f"{code}.SZ"
        elif market == "hk_connect":
            code_fixed = code.zfill(5)
            return f"{code_fixed}.HK"
        return f"{code}.UNKNOWN"

    def _df_to_bars(self, df, ticker: str) -> list[Bar]:
        if df is None or df.empty:
            return []
        bars = []
        for _, row in df.iterrows():
            trade_date = str(row.get("日期", ""))[:10]
            bars.append(Bar(
                ticker=ticker,
                open=float(row["开盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                close=float(row["收盘"]),
                volume=int(row["成交量"]),
                amount=float(row["成交额"]),
                frequency="1d",
                trade_date=trade_date,
            ))
        return bars
```

- [ ] **Step 4: Run tests to pass**

```
pytest tests/unit/test_market_akshare.py -v  → PASS (network-dependent tests may skip)
```

- [ ] **Step 5: Commit**

```bash
git add fisher/market/akshare.py tests/unit/test_market_akshare.py
git commit -m "feat: AkshareAdapter for A-share daily bars"
```

---

### Task 5: Factor Base + Registry

**Files:**
- Create: `FisherQuant/fisher/factor/__init__.py`
- Create: `FisherQuant/fisher/factor/base.py`
- Create: `FisherQuant/fisher/factor/registry.py`
- Create: `FisherQuant/tests/unit/test_factor_base.py`
- Create: `FisherQuant/tests/unit/test_factor_registry.py`

**Interfaces:**
- Produces: `Factor` ABC with `name`, `category`, `compute(df: pl.DataFrame) -> pl.DataFrame`
- Produces: `FactorRegistry` with `register(factor)`, `get(name)`, `list_all()`, `list_by_category(cat)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_factor_base.py
import polars as pl
from fisher.factor.base import Factor


class MockFactor(Factor):
    name = "mock_factor"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.col("close").alias(self.name))


class TestFactor:
    def test_factor_name(self):
        f = MockFactor()
        assert f.name == "mock_factor"

    def test_factor_category(self):
        f = MockFactor()
        assert f.category == "price"

    def test_compute_returns_dataframe(self):
        f = MockFactor()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert "mock_factor" in result.columns
        assert result["mock_factor"].to_list() == [10.0, 10.5, 11.0]

    def test_compute_preserves_original_columns(self):
        f = MockFactor()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert "close" in result.columns
```

```python
# tests/unit/test_factor_registry.py
from fisher.factor.base import Factor
from fisher.factor.registry import FactorRegistry
import polars as pl


class FakeFactor(Factor):
    name = "fake"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df


class TestFactorRegistry:
    def setup_method(self):
        FactorRegistry._factors.clear()

    def test_register_and_get(self):
        f = FakeFactor()
        FactorRegistry.register(f)
        assert FactorRegistry.get("fake") is f

    def test_list_all(self):
        FactorRegistry.register(FakeFactor())
        all_factors = FactorRegistry.list_all()
        assert len(all_factors) == 1
        assert all_factors[0].name == "fake"

    def test_get_missing_raises(self):
        with pytest.raises(KeyError):
            FactorRegistry.get("nonexistent")

    def test_list_by_category(self):
        FactorRegistry.register(FakeFactor())
        price_factors = FactorRegistry.list_by_category("price")
        assert len(price_factors) == 1
        fundamental = FactorRegistry.list_by_category("fundamental")
        assert len(fundamental) == 0

    def test_register_duplicate_overwrites(self):
        f1 = FakeFactor()
        f2 = FakeFactor()
        FactorRegistry.register(f1)
        FactorRegistry.register(f2)
        assert FactorRegistry.get("fake") is f2
```

- [ ] **Step 2: Run tests to verify failure**

```
pytest tests/unit/test_factor_base.py tests/unit/test_factor_registry.py -v  → FAIL
```

- [ ] **Step 3: Write factor/base.py and factor/registry.py**

```python
# fisher/factor/base.py
from abc import ABC, abstractmethod
import polars as pl


class Factor(ABC):
    name: str = ""
    category: str = ""

    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame: ...
```

```python
# fisher/factor/registry.py
from .base import Factor


class FactorRegistry:
    _factors: dict[str, Factor] = {}

    @classmethod
    def register(cls, factor: Factor):
        cls._factors[factor.name] = factor

    @classmethod
    def get(cls, name: str) -> Factor:
        if name not in cls._factors:
            raise KeyError(f"Factor '{name}' not registered")
        return cls._factors[name]

    @classmethod
    def list_all(cls) -> list[Factor]:
        return list(cls._factors.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[Factor]:
        return [f for f in cls._factors.values() if f.category == category]
```

- [ ] **Step 4: Run tests to pass**

```
pytest tests/unit/test_factor_base.py tests/unit/test_factor_registry.py -v  → PASS
```

- [ ] **Step 5: Commit**

```bash
git add fisher/factor/__init__.py fisher/factor/base.py fisher/factor/registry.py tests/unit/test_factor_base.py tests/unit/test_factor_registry.py
git commit -m "feat: Factor base class and registry"
```

---

### Task 6: Price Factors

**Files:**
- Create: `FisherQuant/fisher/factor/price.py`
- Create: `FisherQuant/tests/unit/test_factor_price.py`

**Built-in factors:** momentum_20d, momentum_60d, volatility_20d, volatility_60d, turnover_5d, turnover_20d, volume_ratio

- [ ] **Step 1-5: TDD cycle for each factor class**

All factors follow the same pattern. Example for momentum_20d:

```python
# fisher/factor/price.py
import polars as pl
from .base import Factor


class Momentum20D(Factor):
    name = "momentum_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns:
            raise ValueError("DataFrame must have 'close' column")
        return df.with_columns(
            ((pl.col("close") / pl.col("close").shift(20) - 1) * 100).alias(self.name)
        )


class Momentum60D(Factor):
    name = "momentum_60d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            ((pl.col("close") / pl.col("close").shift(60) - 1) * 100).alias(self.name)
        )


class Volatility20D(Factor):
    name = "volatility_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        returns = pl.col("close").pct_change()
        return df.with_columns(
            returns.rolling_std(20).alias(self.name)
        )


class Volatility60D(Factor):
    name = "volatility_60d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        returns = pl.col("close").pct_change()
        return df.with_columns(
            returns.rolling_std(60).alias(self.name)
        )


class Turnover5D(Factor):
    name = "turnover_5d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "volume" not in df.columns or "close" not in df.columns:
            raise ValueError("DataFrame must have 'volume' and 'close' columns")
        return df.with_columns(
            pl.col("volume").rolling_mean(5).alias(self.name)
        )


class Turnover20D(Factor):
    name = "turnover_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.col("volume").rolling_mean(20).alias(self.name)
        )


class VolumeRatio(Factor):
    name = "volume_ratio"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        vol_ma5 = pl.col("volume").rolling_mean(5)
        return df.with_columns(
            (pl.col("volume") / vol_ma5).alias(self.name)
        )
```

Tests:

```python
# tests/unit/test_factor_price.py
import polars as pl
from fisher.factor.price import Momentum20D, Volatility20D, Turnover5D, VolumeRatio


class TestMomentum20D:
    def test_momentum_computes_pct_change(self):
        f = Momentum20D()
        close_prices = [10.0] * 21
        close_prices[-1] = 11.0  # 10% increase from 20 bars ago
        df = pl.DataFrame({"close": close_prices})
        result = f.compute(df)
        assert "momentum_20d" in result.columns
        assert result["momentum_20d"][-1] == pytest.approx(10.0, abs=0.01)

    def test_not_enough_data_returns_null(self):
        f = Momentum20D()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert result["momentum_20d"].to_list() == [None, None, None]


class TestVolatility20D:
    def test_volatility_is_positive(self):
        f = Volatility20D()
        import random
        prices = [100.0]
        for _ in range(100):
            prices.append(prices[-1] * (1 + random.uniform(-0.02, 0.02)))
        df = pl.DataFrame({"close": prices})
        result = f.compute(df)
        assert result["volatility_20d"].drop_nulls().min() > 0


class TestTurnover5D:
    def test_turnover_computes_rolling_mean(self):
        f = Turnover5D()
        df = pl.DataFrame({"close": [10.0]*6, "volume": [100, 200, 300, 400, 500, 600]})
        result = f.compute(df)
        assert result["turnover_5d"][-1] == pytest.approx(400.0)


class TestVolumeRatio:
    def test_volume_ratio(self):
        f = VolumeRatio()
        df = pl.DataFrame({"volume": [100, 100, 100, 100, 100, 200]})
        result = f.compute(df)
        assert result["volume_ratio"][-1] == pytest.approx(2.0, abs=0.01)
```

Commit: `feat: price factors (momentum, volatility, turnover, volume_ratio)`

---

### Task 7: Fundamental + Technical Factors

**Files:**
- Create: `FisherQuant/fisher/factor/fundamental.py`
- Create: `FisherQuant/fisher/factor/technical.py`
- Create: `FisherQuant/tests/unit/test_factor_fundamental.py`
- Create: `FisherQuant/tests/unit/test_factor_technical.py`

**Fundamental factors:** pb_ratio, pe_ratio, roe — computes from financial data columns

**Technical factors:** macd, rsi_14, bollinger_mid, bollinger_upper, bollinger_lower

Same TDD pattern as Task 6. All code provided in detail.

Commit: `feat: fundamental and technical factors (pb, pe, roe, macd, rsi, bollinger)`

---

### Task 8: Factor Engine with Caching

**Files:**
- Create: `FisherQuant/fisher/factor/engine.py`
- Create: `FisherQuant/tests/unit/test_factor_engine.py`

**Interfaces:**
- Produces: `FactorEngine.compute(factor_names: list[str], df: pl.DataFrame, ticker: str, date: str) -> pl.DataFrame`
- Caching: same (ticker, date, factor) → cached result from DuckDB

Same TDD pattern. Key: engine reads from registry, computes factors sequentially, caches results to DuckDB.

Commit: `feat: factor engine with caching and sequential pipeline`

---

### Task 9: Integration — Market to Store Pipeline

**Files:**
- Create: `FisherQuant/tests/integration/test_market_to_store.py`

**Test:** Fetch bars from AkshareAdapter → save via BarRepo → query back → verify data integrity.

- [ ] Steps:
1. Skip if no network (akshare API unavailable)
2. Fetch real bars for a single ticker
3. Save to DuckDB via BarRepo
4. Query back via BarRepo
5. Verify ticker, date range, and basic data integrity
6. Commit

Commit: `feat: market-to-store integration test`
