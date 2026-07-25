# FisherQuant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-stack quantitative trading system for A-shares + HK Connect, from backtest to live paper trading with web monitoring.

**Architecture:** 14 core + 3 system modules communicating via a dual-mode event bus (asyncio default, Redis optional). DuckDB for storage, polars for computation, FastAPI for monitoring, YAML+pydantic for configuration. Paper Engine is shared between backtest and simulated live trading.

**Tech Stack:** Python 3.11+, polars, DuckDB, FastAPI, asyncio, pydantic v2, pyyaml, akshare, APScheduler, python-jose, passlib, pytest, pytest-asyncio, uv

## Global Constraints

- Python >= 3.11
- Package manager: uv
- Config files: YAML under `configs/`
- Sensitive values: environment variables only, `${ENV_VAR}` in YAML
- Event bus default: asyncio in-process; Redis optional upgrade
- All public functions/methods: type annotations
- All async I/O: `async def` with proper `await`
- Test runner: `pytest` with `pytest-asyncio`
- Logging: structured JSON + terminal color, module-level log levels
- A-shares: T+1, 100-share lots, price limits varying by board
- HK Connect: T+0, variable lots, no price limits, HKD→CNY conversion

---

## File Structure Map

```
FisherQuant/
├── pyproject.toml                              # project metadata, dependencies, scripts
├── fisher/
│   ├── __init__.py                             # empty
│   ├── event/
│   │   ├── __init__.py
│   │   ├── types.py                            # Event dataclasses (all 18 event types)
│   │   └── bus.py                              # EventBus ABC, AsyncioEventBus, RedisEventBus stub
│   ├── config/
│   │   ├── __init__.py
│   │   ├── schemas.py                          # pydantic models for all config sections
│   │   └── loader.py                           # ConfigLoader: YAML + env var + defaults
│   ├── logging/
│   │   ├── __init__.py
│   │   └── setup.py                            # init_logging: structured JSON + terminal handler
│   ├── store/
│   │   ├── __init__.py
│   │   ├── engine.py                           # DuckDBEngine: connection pool, query runner
│   │   ├── schema.py                           # table DDL, versioned migrations
│   │   └── repository.py                       # BarRepo, PositionRepo: typed query methods
│   ├── market/
│   │   ├── __init__.py
│   │   ├── gateway.py                          # MarketGateway ABC, run/stop
│   │   ├── akshare.py                          # AkshareAdapter: implements MarketGateway
│   │   ├── model.py                            # Bar, Quote, Snapshot dataclasses
│   │   └── rules.py                            # ExchangeRules: AShareRules, HKConnectRules, ETFRules, CBRules
│   ├── factor/
│   │   ├── __init__.py
│   │   ├── base.py                             # Factor ABC
│   │   ├── registry.py                         # FactorRegistry: register, discover, list
│   │   ├── engine.py                           # FactorEngine: compute pipeline with caching
│   │   ├── price.py                            # momentum_20d, volatility_60d, turnover_5d, ...
│   │   ├── fundamental.py                      # pb_ratio, pe_ratio, roe, ...
│   │   └── technical.py                        # macd, rsi, bollinger, ...
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py                             # Strategy ABC, lifecycle methods
│   │   ├── registry.py                         # StrategyRegistry: auto-discover, hot-reload
│   │   ├── engine.py                           # StrategyEngine: load, run, pause, resume
│   │   └── pipeline.py                         # PipelineParser: YAML pipeline → Strategy instance
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── builder.py                          # PortfolioBuilder: signals → weights → orders
│   │   └── methods.py                          # equal_weight, risk_parity, kelly
│   ├── paper/
│   │   ├── __init__.py
│   │   ├── engine.py                           # PaperEngine: implements BrokerAdapter
│   │   ├── fill.py                             # FillSimulator: fill probability, liquidity
│   │   └── fees.py                             # FeeCalculator: per-asset-type fee tables
│   ├── oms/
│   │   ├── __init__.py
│   │   ├── orders.py                           # Order, OrderStatus, OrderSide dataclasses
│   │   └── engine.py                           # OMSEngine: order state machine, condition queue
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── adapter.py                          # BrokerAdapter ABC
│   │   └── registry.py                         # BrokerRegistry: register/get
│   ├── position/
│   │   ├── __init__.py
│   │   └── service.py                          # PositionService: holdings, cost basis, snapshots
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── engine.py                           # RiskEngine: pre-trade check + real-time monitor
│   │   ├── pre_trade.py                        # PreTradeRule ABC, MaxPosition, DailyLossLimit, etc.
│   │   ├── realtime.py                         # VaR, beta, drawdown calculators
│   │   └── barra.py                            # BarraAttribution (stub)
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py                           # BacktestEngine: orchestrator
│   │   └── time_player.py                      # TimePlayer: sequential bar replay
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── performance.py                      # sharpe, sortino, max_drawdown, etc.
│   │   ├── attribution.py                      # brinson_attribution
│   │   └── report.py                           # report_to_html, report_to_json, report_to_pdf
│   ├── alert/
│   │   ├── __init__.py
│   │   └── service.py                          # AlertService: routing, throttle, aggregate
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── app.py                              # FastAPI app factory
│   │   ├── auth.py                             # JWT login, password management
│   │   ├── ws.py                               # WebSocket endpoints
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   └── dashboard.py                    # REST endpoints for dashboard data
│   │   └── templates/
│   │       ├── base.html                       # base layout (nav + content block)
│   │       ├── login.html                      # login form
│   │       ├── dashboard.html                  # overview tab
│   │       ├── orders.html                     # orders log tab
│   │       ├── risk.html                       # risk panel tab
│   │       ├── strategy.html                   # strategy status tab
│   │       ├── alerts.html                     # alerts log tab
│   │       └── settings.html                   # change password
│   └── scheduler/
│       ├── __init__.py
│       └── engine.py                           # SchedulerEngine: APScheduler jobs
├── configs/
│   ├── system.yaml                             # mode, event backend, logging
│   ├── market.yaml                             # source, refresh, rate_limit
│   ├── strategy.yaml                           # pipelines, portfolio method
│   ├── risk.yaml                               # pre-trade rules, realtime thresholds
│   ├── fees.yaml                               # per-asset-type fee tables
│   ├── alert.yaml                              # routing, throttle
│   ├── benchmark.yaml                          # benchmark tickers
│   └── broker.yaml                             # broker config (paper default)
└── tests/
    ├── __init__.py
    ├── conftest.py                             # shared fixtures (event_bus, config, duckdb)
    ├── unit/
    │   ├── __init__.py
    │   ├── test_config_loader.py
    │   ├── test_config_schemas.py
    │   ├── test_logging.py
    │   ├── test_event_bus.py
    │   ├── test_event_types.py
    │   ├── test_store_engine.py
    │   ├── test_store_schema.py
    │   ├── test_store_repository.py
    │   ├── test_market_rules.py
    │   ├── test_factor_registry.py
    │   ├── test_factor_engine.py
    │   ├── test_factor_price.py
    │   ├── test_strategy_base.py
    │   ├── test_strategy_registry.py
    │   ├── test_portfolio_builder.py
    │   ├── test_paper_fees.py
    │   ├── test_paper_fill.py
    │   ├── test_oms_engine.py
    │   ├── test_position_service.py
    │   ├── test_risk_pre_trade.py
    │   ├── test_backtest_time_player.py
    │   ├── test_analytics_performance.py
    │   ├── test_alert_service.py
    │   └── test_monitor_auth.py
    ├── integration/
    │   ├── __init__.py
    │   ├── test_signal_to_order_flow.py
    │   ├── test_order_to_position_flow.py
    │   └── test_event_bus_integration.py
    └── validation/
        ├── __init__.py
        └── data/
            └── test_double_ma.csv              # small fixed dataset (10 bars, 2 stocks)
```

---

## Phase 1: Infrastructure Foundation

*Dependencies: None — this is the first phase.*

### Task 1: Project Scaffolding

**Files:**
- Create: `FisherQuant/pyproject.toml`
- Create: `FisherQuant/fisher/__init__.py`
- Create: `FisherQuant/tests/__init__.py`

**Interfaces:**
- Produces: `pyproject.toml` with all dependencies for the entire project, `fisher` package, `tests` package

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "fisherquant"
version = "0.1.0"
description = "Quantitative trading system for A-shares and HK Connect"
requires-python = ">=3.11"
dependencies = [
    "polars",
    "duckdb>=1.0",
    "pyyaml",
    "pydantic>=2.0",
    "fastapi",
    "uvicorn[standard]",
    "websockets",
    "jinja2",
    "python-multipart",
    "python-jose[cryptography]",
    "passlib[bcrypt]",
    "apscheduler",
    "akshare",
    "httpx",
    "pyarrow",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "mypy",
    "ruff",
]

[project.scripts]
fisher = "fisher.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 2: Create fisher/__init__.py and tests/__init__.py**

Run:
```bash
New-Item -ItemType File -Path "FisherQuant\fisher\__init__.py"
New-Item -ItemType File -Path "FisherQuant\tests\__init__.py"
$content = '__version__ = "0.1.0"'; Set-Content -LiteralPath "FisherQuant\fisher\__init__.py" -Value $content
```

- [ ] **Step 3: Verify package is installable**

Run: `uv pip install -e .` in FisherQuant directory
Expected: dependencies install without error

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml fisher/__init__.py tests/__init__.py
git commit -m "feat: project scaffolding with pyproject.toml"
```

---

### Task 2: Configuration Schemas (Pydantic Models)

**Files:**
- Create: `FisherQuant/fisher/config/__init__.py`
- Create: `FisherQuant/fisher/config/schemas.py`
- Create: `FisherQuant/tests/unit/test_config_schemas.py`

**Interfaces:**
- Produces: `AppConfig` pydantic model with nested sections: `SystemConfig`, `EventConfig`, `LoggingConfig`, `MarketConfig`, `StrategyConfig`, `RiskConfig`, `FeesConfig`, `AlertConfig`, `BenchmarkConfig`, `BrokerConfig`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_schemas.py
import pytest
from pydantic import ValidationError
from fisher.config.schemas import (
    EventConfig, LoggingConfig, MarketConfig, SystemConfig,
    RiskConfig, AlertConfig, BenchmarkConfig, BrokerConfig,
    FeesConfig, StrategyConfig, AppConfig, RunMode,
)


class TestEventConfig:
    def test_defaults(self):
        c = EventConfig()
        assert c.backend == "asyncio"
        assert c.redis_url is None

    def test_redis_backend_requires_url(self):
        with pytest.raises(ValidationError):
            EventConfig(backend="redis")


class TestLoggingConfig:
    def test_defaults(self):
        c = LoggingConfig()
        assert c.level == "INFO"
        assert c.dir == "logs/"
        assert c.rotation == "daily"
        assert c.retention == "90d"
        assert c.structured is True

    def test_module_levels_default_is_dict(self):
        c = LoggingConfig()
        assert isinstance(c.modules, dict)


class TestSystemConfig:
    def test_defaults(self):
        c = SystemConfig()
        assert c.mode == RunMode.PAPER
        assert isinstance(c.event, EventConfig)
        assert isinstance(c.logging, LoggingConfig)

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError):
            SystemConfig(mode="invalid")


class TestMarketConfig:
    def test_defaults(self):
        c = MarketConfig()
        assert c.source == "akshare"
        assert c.refresh.quote == 3
        assert c.rate_limit.max_per_second == 2


class TestRiskConfig:
    def test_defaults(self):
        c = RiskConfig()
        assert len(c.pre_trade) > 0
        assert c.realtime.var_confidence == 0.99
        assert c.realtime.max_drawdown == 0.15


class TestFeesConfig:
    def test_default_has_all_asset_types(self):
        c = FeesConfig()
        assert "a_share" in c.assets
        assert "etf" in c.assets
        assert "convertible_bond" in c.assets
        assert "hk_connect" in c.assets


class TestAlertConfig:
    def test_default_channels(self):
        c = AlertConfig()
        assert "console" in c.channels


class TestBenchmarkConfig:
    def test_default_benchmarks(self):
        c = BenchmarkConfig()
        assert len(c.benchmarks) == 1
        assert c.benchmarks[0].ticker == "000300.SH"


class TestBrokerConfig:
    def test_default_is_paper(self):
        c = BrokerConfig()
        assert c.name == "paper"


class TestAppConfig:
    def test_constructs_from_partial_dict(self):
        data = {"system": {"mode": "backtest"}}
        c = AppConfig(**data)
        assert c.system.mode == RunMode.BACKTEST

    def test_fee_for_asset_type(self):
        c = AppConfig()
        a_share_fee = c.fees.assets["a_share"]
        assert a_share_fee.commission_rate == 0.00025
        assert a_share_fee.stamp_duty == 0.0005
        assert a_share_fee.stamp_duty_side == "sell"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_config_schemas.py -v`
Expected: ImportError (module not found)

- [ ] **Step 3: Write config/schemas.py**

```python
# fisher/config/schemas.py
from enum import Enum
from typing import Optional
from pydantic import BaseModel, model_validator


class RunMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class EventConfig(BaseModel):
    backend: str = "asyncio"
    redis_url: Optional[str] = None

    @model_validator(mode="after")
    def redis_needs_url(self):
        if self.backend == "redis" and not self.redis_url:
            raise ValueError("redis_url is required when backend is 'redis'")
        return self


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir: str = "logs/"
    rotation: str = "daily"
    retention: str = "90d"
    structured: bool = True
    modules: dict[str, str] = {"strategy": "DEBUG", "risk": "INFO", "market": "WARNING"}


class SystemConfig(BaseModel):
    mode: RunMode = RunMode.PAPER
    event: EventConfig = EventConfig()
    logging: LoggingConfig = LoggingConfig()


class RefreshConfig(BaseModel):
    quote: int = 3
    bars_daily: str = "16:30"
    bars_minute: Optional[str] = None


class RateLimitConfig(BaseModel):
    max_per_second: int = 2
    on_limit: str = "sleep_and_retry"


class MarketConfig(BaseModel):
    source: str = "akshare"
    refresh: RefreshConfig = RefreshConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()


class InvestmentUniverse(BaseModel):
    tickers: list[str] = []
    exclude_st: bool = True
    exclude_new: bool = True


class PortfolioMethodConfig(BaseModel):
    method: str = "equal_weight"
    rebalance: str = "weekly"
    max_positions: int = 20
    conflict_mode: str = "weighted_merge"


class StrategyConfig(BaseModel):
    universe: InvestmentUniverse = InvestmentUniverse()
    strategies: list[dict] = []
    portfolio: PortfolioMethodConfig = PortfolioMethodConfig()


class PreTradeRuleConfig(BaseModel):
    rule: str
    params: dict = {}


class RealtimeRiskConfig(BaseModel):
    var_confidence: float = 0.99
    max_drawdown: float = 0.15
    beta_limit: float = 1.5


class RiskConfig(BaseModel):
    pre_trade: list[PreTradeRuleConfig] = []
    realtime: RealtimeRiskConfig = RealtimeRiskConfig()
    blacklist: list[str] = []


class AssetFeeConfig(BaseModel):
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_duty: float = 0.0
    stamp_duty_side: str = "none"
    transfer_fee: float = 0.0
    regulatory_fee: float = 0.0
    settlement_fee: float = 0.0


class FeesConfig(BaseModel):
    assets: dict[str, AssetFeeConfig] = {}


class AlertChannelConfig(BaseModel):
    type: str = "console"
    webhook: Optional[str] = None
    events: list[str] = []
    level: str = "INFO"
    throttle: int = 60


class AlertConfig(BaseModel):
    channels: dict[str, AlertChannelConfig] = {}


class BenchmarkItem(BaseModel):
    name: str
    ticker: str
    weight: float = 1.0


class BenchmarkConfig(BaseModel):
    benchmarks: list[BenchmarkItem] = [BenchmarkItem(name="CSI300", ticker="000300.SH")]


class BrokerConfig(BaseModel):
    name: str = "paper"
    params: dict = {}


class AppConfig(BaseModel):
    system: SystemConfig = SystemConfig()
    market: MarketConfig = MarketConfig()
    strategy: StrategyConfig = StrategyConfig()
    risk: RiskConfig = RiskConfig()
    fees: FeesConfig = FeesConfig()
    alert: AlertConfig = AlertConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()
    broker: BrokerConfig = BrokerConfig()
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_config_schemas.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/config/__init__.py fisher/config/schemas.py tests/unit/test_config_schemas.py
git commit -m "feat: config schemas with pydantic models"
```

---

### Task 3: Configuration Loader (YAML + env)

**Files:**
- Create: `FisherQuant/tests/unit/test_config_loader.py`
- Modify: `FisherQuant/fisher/config/loader.py` (create)

**Interfaces:**
- Produces: `ConfigLoader.load(config_dir: str) -> AppConfig` — reads all YAML files, resolves `${ENV_VAR}`, merges with defaults, validates

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_loader.py
import os
import tempfile
from pathlib import Path
from fisher.config.loader import ConfigLoader, ConfigLoadError


class TestConfigLoader:
    def test_loads_defaults_when_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ConfigLoader.load(d)
            assert cfg.system.mode.value == "paper"
            assert cfg.market.source == "akshare"

    def test_overrides_from_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("mode: backtest")
            cfg = ConfigLoader.load(d)
            assert cfg.system.mode.value == "backtest"
            assert cfg.market.source == "akshare"

    def test_env_var_substitution(self):
        os.environ["TEST_REDIS_URL"] = "redis://localhost:6379"
        try:
            with tempfile.TemporaryDirectory() as d:
                Path(d, "system.yaml").write_text(
                    "event:\n  backend: redis\n  redis_url: ${TEST_REDIS_URL}"
                )
                cfg = ConfigLoader.load(d)
                assert cfg.system.event.redis_url == "redis://localhost:6379"
        finally:
            del os.environ["TEST_REDIS_URL"]

    def test_missing_env_var_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("event:\n  redis_url: ${MISSING_VAR}")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass

    def test_merges_fees_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "fees.yaml").write_text("""
assets:
  a_share:
    commission_rate: 0.0001
""")
            cfg = ConfigLoader.load(d)
            assert cfg.fees.assets["a_share"].commission_rate == 0.0001

    def test_invalid_yaml_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text(": invalid yaml :")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass

    def test_invalid_config_values_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("mode: invalid_mode")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_config_loader.py::TestConfigLoader::test_loads_defaults_when_no_files -v`
Expected: FAIL

- [ ] **Step 3: Write config/loader.py**

```python
# fisher/config/loader.py
import os
import re
from pathlib import Path
import yaml
from pydantic import ValidationError
from .schemas import AppConfig


class ConfigLoadError(Exception):
    pass


_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(obj):
    if isinstance(obj, str):
        def replace(match):
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                raise ConfigLoadError(f"Environment variable '{var}' not set")
            return val
        return _ENV_VAR_RE.sub(replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


_CONFIG_FILES = [
    "system.yaml", "market.yaml", "strategy.yaml",
    "risk.yaml", "fees.yaml", "alert.yaml",
    "benchmark.yaml", "broker.yaml",
]


class ConfigLoader:
    @staticmethod
    def load(config_dir: str) -> AppConfig:
        config_dir = Path(config_dir)
        raw: dict[str, dict] = {}

        for fname in _CONFIG_FILES:
            fpath = config_dir / fname
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                    if loaded:
                        raw[fname.replace(".yaml", "")] = loaded
                except yaml.YAMLError as e:
                    raise ConfigLoadError(f"Invalid YAML in {fname}: {e}")

        raw = _resolve_env_vars(raw)

        try:
            return AppConfig(
                system=raw.get("system"),
                market=raw.get("market"),
                strategy=raw.get("strategy"),
                risk=raw.get("risk"),
                fees=raw.get("fees"),
                alert=raw.get("alert"),
                benchmark=raw.get("benchmark"),
                broker=raw.get("broker"),
            )
        except ValidationError as e:
            raise ConfigLoadError(f"Config validation failed: {e}")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_config_loader.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/config/loader.py tests/unit/test_config_loader.py
git commit -m "feat: config loader with YAML and env var resolution"
```

---

### Task 4: Default YAML Configuration Files

**Files:**
- Create: `FisherQuant/configs/system.yaml`
- Create: `FisherQuant/configs/market.yaml`
- Create: `FisherQuant/configs/strategy.yaml`
- Create: `FisherQuant/configs/risk.yaml`
- Create: `FisherQuant/configs/fees.yaml`
- Create: `FisherQuant/configs/alert.yaml`
- Create: `FisherQuant/configs/benchmark.yaml`
- Create: `FisherQuant/configs/broker.yaml`

**Interfaces:**
- Consumes: `AppConfig` schema (from Task 2)
- Produces: 8 YAML files matching schema defaults with sensible overrides

- [ ] **Step 1: Write configs/system.yaml**

```yaml
# configs/system.yaml
mode: paper

event:
  backend: asyncio

logging:
  level: INFO
  dir: logs/
  rotation: daily
  retention: 90d
  structured: true
  modules:
    strategy: DEBUG
    risk: INFO
    market: WARNING
```

- [ ] **Step 2: Write configs/market.yaml**

```yaml
# configs/market.yaml
source: akshare

refresh:
  quote: 3
  bars_daily: "16:30"
  bars_minute: null

rate_limit:
  max_per_second: 2
  on_limit: sleep_and_retry
```

- [ ] **Step 3: Write configs/strategy.yaml**

```yaml
# configs/strategy.yaml
universe:
  tickers: []
  exclude_st: true
  exclude_new: true

strategies: []

portfolio:
  method: equal_weight
  rebalance: weekly
  max_positions: 20
  conflict_mode: weighted_merge
```

- [ ] **Step 4: Write configs/risk.yaml**

```yaml
# configs/risk.yaml
pre_trade:
  - rule: MaxPosition
    params:
      max_pct: 0.2
  - rule: DailyLossLimit
    params:
      max_loss_pct: 0.05
  - rule: PriceLimit
  - rule: SectorLimit
    params:
      max_pct: 0.3

realtime:
  var_confidence: 0.99
  max_drawdown: 0.15
  beta_limit: 1.5

blacklist: []
```

- [ ] **Step 5: Write configs/fees.yaml**

```yaml
# configs/fees.yaml
assets:
  a_share:
    commission_rate: 0.00025
    min_commission: 5.0
    stamp_duty: 0.0005
    stamp_duty_side: sell
    transfer_fee: 0.00001
    regulatory_fee: 0.0000687

  etf:
    commission_rate: 0.0001
    min_commission: 1.0
    stamp_duty: 0.0
    stamp_duty_side: none

  convertible_bond:
    commission_rate: 0.00005
    min_commission: 1.0
    stamp_duty: 0.0
    stamp_duty_side: none

  hk_connect:
    commission_rate: 0.00025
    min_commission: 100.0
    stamp_duty: 0.001
    stamp_duty_side: both
    regulatory_fee: 0.0000835
    settlement_fee: 0.00002
```

- [ ] **Step 6: Write configs/alert.yaml**

```yaml
# configs/alert.yaml
channels:
  console:
    type: console
    events: [RiskAlert, OrderFilled, OrderRejected, SystemError]
    level: WARN
    throttle: 60
```

- [ ] **Step 7: Write configs/benchmark.yaml**

```yaml
# configs/benchmark.yaml
benchmarks:
  - name: CSI300
    ticker: "000300.SH"
    weight: 1.0
```

- [ ] **Step 8: Write configs/broker.yaml**

```yaml
# configs/broker.yaml
name: paper
params: {}
```

- [ ] **Step 9: Verify config loading works**

Run:
```python -c "from fisher.config.loader import ConfigLoader; c = ConfigLoader.load('configs'); print(c.system.mode)"```
Expected: `paper`

- [ ] **Step 10: Commit**

```bash
git add configs/*.yaml
git commit -m "feat: default YAML configuration files"
```

---

### Task 5: Logging Setup

**Files:**
- Create: `FisherQuant/fisher/logging/__init__.py`
- Create: `FisherQuant/fisher/logging/setup.py`
- Create: `FisherQuant/tests/unit/test_logging.py`

**Interfaces:**
- Consumes: `LoggingConfig` (from Task 2)
- Produces: `init_logging(cfg: LoggingConfig) -> None` — configures root logger with structured JSON handler + terminal color handler

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_logging.py
import json
import logging
import tempfile
from pathlib import Path
from fisher.logging.setup import init_logging
from fisher.config.schemas import LoggingConfig


class TestInitLogging:
    def test_json_handler_writes_structured(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = LoggingConfig(dir=d, rotation="1h", retention="1d")
            init_logging(cfg)

            logger = logging.getLogger("test_json")
            logger.info("hello", extra={"key": "val"})

            logs = list(Path(d).glob("*.log*"))
            assert len(logs) > 0
            line = logs[0].read_text()
            record = json.loads(line)
            assert record["message"] == "hello"
            assert record.get("key") == "val"

    def test_module_level_override(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = LoggingConfig(
                dir=d, rotation="1h", retention="1d",
                modules={"test_mod": "WARNING"}
            )
            init_logging(cfg)

            logger = logging.getLogger("test_mod")
            assert logger.level == logging.WARNING

    def test_root_level_is_set(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = LoggingConfig(dir=d, level="DEBUG")
            init_logging(cfg)

            root = logging.getLogger()
            assert root.level == logging.DEBUG
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_logging.py -v`
Expected: all FAIL

- [ ] **Step 3: Write logging/setup.py**

```python
# fisher/logging/setup.py
import json
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from .schemas import LoggingConfig


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, self.datefmt),
            "module": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in ("args", "asctime", "created", "exc_info", "exc_text",
                           "filename", "funcName", "id", "levelname", "levelno",
                           "lineno", "module", "msecs", "message", "msg",
                           "name", "pathname", "process", "processName",
                           "relativeCreated", "stack_info", "thread", "threadName"):
                base[key] = val
        return json.dumps(base, ensure_ascii=False, default=str)


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        msg = f"{record.asctime} [{record.name}] {record.levelname}: {record.getMessage()}"
        if sys.stderr.isatty():
            return f"{color}{msg}{self.RESET}"
        return msg


def init_logging(cfg: LoggingConfig) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))

    log_dir = Path(cfg.dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    json_log = log_dir / "fisher.log"
    json_handler = TimedRotatingFileHandler(
        str(json_log), when=cfg.rotation[0], backupCount=30
    )
    json_handler.setFormatter(_StructuredFormatter())
    root.addHandler(json_handler)

    term_handler = logging.StreamHandler(sys.stderr)
    term_handler.setFormatter(_ColorFormatter())
    root.addHandler(term_handler)

    for mod_name, level in cfg.modules.items():
        logging.getLogger(mod_name).setLevel(
            getattr(logging, level.upper(), logging.DEBUG)
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_logging.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/logging/__init__.py fisher/logging/setup.py tests/unit/test_logging.py
git commit -m "feat: structured logging with JSON + terminal color handlers"
```

---

### Task 6: Event Type Definitions

**Files:**
- Create: `FisherQuant/fisher/event/__init__.py`
- Create: `FisherQuant/fisher/event/types.py`
- Create: `FisherQuant/tests/unit/test_event_types.py`

**Interfaces:**
- Produces: 18 event dataclasses: `MarketSnapshot`, `Bar`, `Signal`, `OrderPending`, `OrderAcked`, `OrderPartiallyFilled`, `OrderFilled`, `OrderRejected`, `OrderCancelled`, `PositionUpdate`, `RiskAlert`, `MarketOpen`, `MarketClose`, `MarketMidBreak`, `MarketMidResume`, `DividendEvent`, `SplitEvent`, `SuspensionEvent`, `ResumptionEvent`, `SystemError`
- All events extend base `Event` with `timestamp: float`
- Each event has a `__event_type__: str` class attribute for routing

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_event_types.py
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_event_types.py -v`
Expected: all FAIL

- [ ] **Step 3: Write event/types.py**

```python
# fisher/event/types.py
from dataclasses import dataclass, field
from enum import Enum
import time as _time


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    NEW = "new"
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKED = "acked"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class Event:
    timestamp: float = field(default_factory=_time.time)
    __event_type__: str = field(default="event", init=False, repr=False)


@dataclass
class MarketSnapshot(Event):
    __event_type__ = "market_snapshot"
    ticker: str = ""
    market: str = "a_share"
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    pre_close: float = 0.0


@dataclass
class Bar(Event):
    __event_type__ = "bar"
    ticker: str = ""
    market: str = "a_share"
    frequency: str = "1d"
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    amount: float = 0.0
    bar_time: float = 0.0


@dataclass
class Signal(Event):
    __event_type__ = "signal"
    strategy: str = ""
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    limit_price: float = 0.0
    confidence: float = 1.0
    reason: str = ""


@dataclass
class OrderPending(Event):
    __event_type__ = "order_pending"
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    price: float = 0.0
    order_type: str = "limit"
    status: OrderStatus = OrderStatus.PENDING


@dataclass
class OrderAcked(Event):
    __event_type__ = "order_acked"
    order_id: str = ""
    broker_order_id: str = ""


@dataclass
class OrderPartiallyFilled(Event):
    __event_type__ = "order_partially_filled"
    order_id: str = ""
    filled_qty: int = 0
    filled_price: float = 0.0
    remaining_qty: int = 0
    commission: float = 0.0


@dataclass
class OrderFilled(Event):
    __event_type__ = "order_filled"
    order_id: str = ""
    ticker: str = ""
    filled_qty: int = 0
    filled_price: float = 0.0
    commission: float = 0.0


@dataclass
class OrderRejected(Event):
    __event_type__ = "order_rejected"
    order_id: str = ""
    ticker: str = ""
    reason: str = ""


@dataclass
class OrderCancelled(Event):
    __event_type__ = "order_cancelled"
    order_id: str = ""


@dataclass
class PositionUpdate(Event):
    __event_type__ = "position_update"
    ticker: str = ""
    market: str = "a_share"
    asset_type: str = "stock"
    quantity: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    available: int = 0


@dataclass
class RiskAlert(Event):
    __event_type__ = "risk_alert"
    rule: str = ""
    ticker: str | None = None
    severity: str = "WARN"
    message: str = ""


@dataclass
class MarketOpen(Event):
    __event_type__ = "market_open"
    market: str = "a_share"


@dataclass
class MarketClose(Event):
    __event_type__ = "market_close"
    market: str = "a_share"


@dataclass
class MarketMidBreak(Event):
    __event_type__ = "market_mid_break"
    market: str = "a_share"


@dataclass
class MarketMidResume(Event):
    __event_type__ = "market_mid_resume"
    market: str = "a_share"


@dataclass
class DividendEvent(Event):
    __event_type__ = "dividend_event"
    ticker: str = ""
    ex_date: str = ""
    cash_per_share: float = 0.0
    bonus_ratio: float = 0.0


@dataclass
class SplitEvent(Event):
    __event_type__ = "split_event"
    ticker: str = ""
    effective_date: str = ""
    split_ratio: float = 1.0


@dataclass
class SuspensionEvent(Event):
    __event_type__ = "suspension_event"
    ticker: str = ""
    market: str = "a_share"


@dataclass
class ResumptionEvent(Event):
    __event_type__ = "resumption_event"
    ticker: str = ""
    market: str = "a_share"


@dataclass
class SystemError(Event):
    __event_type__ = "system_error"
    module: str = ""
    error: str = ""
    detail: str = ""
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_event_types.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/event/__init__.py fisher/event/types.py tests/unit/test_event_types.py
git commit -m "feat: event type definitions with 18 event dataclasses"
```

---

### Task 7: Event Bus (Asyncio + Redis Stub)

**Files:**
- Create: `FisherQuant/fisher/event/bus.py`
- Create: `FisherQuant/tests/unit/test_event_bus.py`

**Interfaces:**
- Consumes: `EventConfig`, event types from Task 6
- Produces: `EventBus` ABC with methods: `subscribe(event_type: str, handler: Callable)`, `unsubscribe(event_type: str, handler: Callable)`, `publish(event: Event) -> None`
- Produces: `AsyncioEventBus` — in-process event routing
- Produces: `RedisEventBus` — stub (raises NotImplementedError for now)
- Factory: `create_event_bus(cfg: EventConfig) -> EventBus`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_event_bus.py
import asyncio
import pytest
from fisher.event.bus import AsyncioEventBus, create_event_bus
from fisher.config.schemas import EventConfig
from fisher.event.types import Bar, Signal, OrderSide


class TestAsyncioEventBus:
    def test_subscribe_and_publish(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("bar", handler)
        bar = Bar(ticker="000001.SZ", close=10.0)
        bus.publish(bar)

        assert len(received) == 0  # handlers run async via create_task

    @pytest.mark.asyncio
    async def test_handler_receives_event(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(event: Bar):
            received.append(event)

        bus.subscribe("bar", handler)
        bar = Bar(ticker="000001.SZ", close=10.0)
        bus.publish(bar)

        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].ticker == "000001.SZ"
        assert received[0].close == 10.0

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        bus = AsyncioEventBus()
        r1, r2 = [], []

        async def h1(e): r1.append(e)
        async def h2(e): r2.append(e)

        bus.subscribe("signal", h1)
        bus.subscribe("signal", h2)
        sig = Signal(strategy="test", ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, confidence=1.0)
        bus.publish(sig)
        await asyncio.sleep(0.01)

        assert len(r1) == 1
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_wrong_event_type_not_delivered(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(e): received.append(e)

        bus.subscribe("bar", handler)
        sig = Signal(strategy="test", ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, confidence=1.0)
        bus.publish(sig)
        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(e): received.append(e)

        bus.subscribe("bar", handler)
        bus.unsubscribe("bar", handler)
        bus.publish(Bar(ticker="000001.SZ", close=10.0))
        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self):
        bus = AsyncioEventBus()
        r2 = []

        async def bad_handler(e): raise RuntimeError("crash")
        async def good_handler(e): r2.append(e)

        bus.subscribe("bar", bad_handler)
        bus.subscribe("bar", good_handler)
        bus.publish(Bar(ticker="000001.SZ", close=10.0))
        await asyncio.sleep(0.01)

        assert len(r2) == 1  # good handler still runs


class TestCreateEventBus:
    def test_creates_asyncio_by_default(self):
        bus = create_event_bus(EventConfig(backend="asyncio"))
        assert isinstance(bus, AsyncioEventBus)

    def test_redis_stub_raises(self):
        with pytest.raises(NotImplementedError):
            create_event_bus(EventConfig(backend="redis", redis_url="redis://localhost"))
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_event_bus.py -v`
Expected: all FAIL

- [ ] **Step 3: Write event/bus.py**

```python
# fisher/event/bus.py
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from collections import defaultdict
from .types import Event
from ..config.schemas import EventConfig

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus(ABC):
    @abstractmethod
    def subscribe(self, event_type: str, handler: Handler) -> None: ...

    @abstractmethod
    def unsubscribe(self, event_type: str, handler: Handler) -> None: ...

    @abstractmethod
    def publish(self, event: Event) -> None: ...


class AsyncioEventBus(EventBus):
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        event_type = event.__event_type__
        for handler in self._handlers.get(event_type, []):
            asyncio.ensure_future(self._safe_call(handler, event))

    async def _safe_call(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Handler for event %s raised exception",
                event.__event_type__,
            )


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str):
        raise NotImplementedError("Redis event bus not yet implemented")

    def subscribe(self, event_type: str, handler: Handler) -> None:
        raise NotImplementedError

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        raise NotImplementedError

    def publish(self, event: Event) -> None:
        raise NotImplementedError


def create_event_bus(cfg: EventConfig) -> EventBus:
    if cfg.backend == "redis":
        return RedisEventBus(cfg.redis_url or "")
    return AsyncioEventBus()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_event_bus.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/event/bus.py tests/unit/test_event_bus.py
git commit -m "feat: asyncio event bus with subscribe/publish/unsubscribe"
```

---

### Task 8: DuckDB Storage Engine

**Files:**
- Create: `FisherQuant/fisher/store/__init__.py`
- Create: `FisherQuant/fisher/store/engine.py`
- Create: `FisherQuant/tests/unit/test_store_engine.py`

**Interfaces:**
- Produces: `DuckDBEngine` class with methods:
  - `__init__(path: str)` — opens/reuses single DuckDB connection
  - `execute(sql: str, params: list = []) -> duckdb.DuckDBPyRelation`
  - `execute_many(sql: str, params_list: list) -> None`
  - `query_df(sql: str, params: list = []) -> polars.DataFrame`
  - `close() -> None`
  - `connection` property — returns raw duckdb connection

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_store_engine.py
import tempfile
from pathlib import Path
import polars as pl
from fisher.store.engine import DuckDBEngine


class TestDuckDBEngine:
    def test_execute_creates_table(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, name VARCHAR)")
            result = engine.query_df("SELECT * FROM test")
            assert len(result) == 0
            assert list(result.columns) == ["id", "name"]

    def test_insert_and_query(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, value DOUBLE)")
            engine.execute("INSERT INTO test VALUES (1, 10.5), (2, 20.0)")
            result = engine.query_df("SELECT * FROM test ORDER BY id")
            assert len(result) == 2
            assert result["value"].to_list() == [10.5, 20.0]

    def test_execute_many(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, value DOUBLE)")
            engine.execute_many(
                "INSERT INTO test VALUES (?, ?)",
                [[1, 10.0], [2, 20.0], [3, 30.0]],
            )
            result = engine.query_df("SELECT COUNT(*) AS cnt FROM test")
            assert result["cnt"][0] == 3

    def test_query_df_returns_polars(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER)")
            engine.execute("INSERT INTO test VALUES (1)")
            df = engine.query_df("SELECT * FROM test")
            assert isinstance(df, pl.DataFrame)
            assert df["id"].dtype == pl.Int32

    def test_persistence_across_connections(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine1 = DuckDBEngine(db_path)
            engine1.execute("CREATE TABLE test (x INTEGER)")
            engine1.execute("INSERT INTO test VALUES (42)")
            engine1.close()

            engine2 = DuckDBEngine(db_path)
            result = engine2.query_df("SELECT x FROM test")
            assert result["x"][0] == 42
            engine2.close()

    def test_connection_property(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            engine.execute("CREATE TABLE test (id INTEGER)")
            conn = engine.connection
            conn.execute("INSERT INTO test VALUES (99)")
            result = engine.query_df("SELECT id FROM test")
            assert result["id"][0] == 99
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_store_engine.py -v`
Expected: all FAIL

- [ ] **Step 3: Write store/engine.py**

```python
# fisher/store/engine.py
import threading
from typing import Any
import duckdb
import polars as pl


class DuckDBEngine:
    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = duckdb.connect(path)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    def execute(self, sql: str, params: list = []) -> duckdb.DuckDBPyRelation:
        return self._conn.execute(sql, params)

    def execute_many(self, sql: str, params_list: list[list]) -> None:
        with self._lock:
            self._conn.executemany(sql, params_list)

    def query_df(self, sql: str, params: list = []) -> pl.DataFrame:
        rel = self._conn.sql(sql, params=params)
        return rel.pl()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_store_engine.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/store/__init__.py fisher/store/engine.py tests/unit/test_store_engine.py
git commit -m "feat: DuckDB storage engine with polars integration"
```

---

### Task 9: DuckDB Schema & Migration

**Files:**
- Create: `FisherQuant/fisher/store/schema.py`
- Create: `FisherQuant/tests/unit/test_store_schema.py`

**Interfaces:**
- Consumes: `DuckDBEngine` (from Task 8)
- Produces: `init_schema(engine: DuckDBEngine) -> None` — creates all tables if not exist
- Produces: `SCHEMA_VERSION = 1`
- Produces: `migrate(engine: DuckDBEngine) -> None` — runs applicable migrations

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_store_schema.py
import tempfile
from pathlib import Path
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema, SCHEMA_VERSION


class TestInitSchema:
    def test_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            tables = engine.query_df(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            )
            table_names = set(tables["table_name"].to_list())
            expected = {
                "schema_version", "bars_daily", "bars_minute",
                "snapshots", "orders", "positions",
                "corporate_actions", "position_snapshots",
            }
            assert expected.issubset(table_names)

    def test_sets_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            row = engine.query_df("SELECT version FROM schema_version")
            assert row["version"][0] == SCHEMA_VERSION

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            init_schema(engine)  # should not raise

            row = engine.query_df("SELECT COUNT(*) AS c FROM schema_version")
            assert row["c"][0] == 1


class TestBarsDailyTable:
    def test_insert_and_query_bars_daily(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            engine.execute("""
                INSERT INTO bars_daily (ticker, trade_date, open, high, low, close, volume, amount, market)
                VALUES ('000001.SZ', '2025-01-02', 10.0, 11.0, 9.8, 10.5, 1000000, 10500000, 'a_share')
            """)

            result = engine.query_df(
                "SELECT ticker, close, volume FROM bars_daily WHERE ticker='000001.SZ'"
            )
            assert len(result) == 1
            assert result["close"][0] == 10.5


class TestOrdersTable:
    def test_insert_and_query_order(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            engine.execute("""
                INSERT INTO orders (order_id, ticker, side, quantity, price, status, market, asset_type)
                VALUES ('oid-1', '000001.SZ', 'buy', 100, 10.5, 'pending', 'a_share', 'stock')
            """)

            result = engine.query_df("SELECT status FROM orders WHERE order_id='oid-1'")
            assert result["status"][0] == "pending"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_store_schema.py -v`
Expected: all FAIL

- [ ] **Step 3: Write store/schema.py**

```python
# fisher/store/schema.py
from .engine import DuckDBEngine

SCHEMA_VERSION = 1

_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars_daily (
        ticker VARCHAR NOT NULL,
        trade_date DATE NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume BIGINT NOT NULL,
        amount DOUBLE NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        adj_factor DOUBLE DEFAULT 1.0,
        PRIMARY KEY (ticker, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars_minute (
        ticker VARCHAR NOT NULL,
        bar_time TIMESTAMP NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume BIGINT NOT NULL,
        amount DOUBLE NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        PRIMARY KEY (ticker, bar_time)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        ticker VARCHAR NOT NULL,
        ts TIMESTAMP NOT NULL,
        last_price DOUBLE,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        volume BIGINT,
        amount DOUBLE,
        pre_close DOUBLE,
        market VARCHAR DEFAULT 'a_share',
        PRIMARY KEY (ticker, ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id VARCHAR PRIMARY KEY,
        ticker VARCHAR NOT NULL,
        side VARCHAR NOT NULL,
        quantity INTEGER NOT NULL,
        price DOUBLE,
        filled_qty INTEGER DEFAULT 0,
        filled_price DOUBLE,
        commission DOUBLE DEFAULT 0.0,
        status VARCHAR DEFAULT 'new',
        order_type VARCHAR DEFAULT 'limit',
        market VARCHAR DEFAULT 'a_share',
        asset_type VARCHAR DEFAULT 'stock',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        ticker VARCHAR NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        asset_type VARCHAR DEFAULT 'stock',
        quantity INTEGER DEFAULT 0,
        avg_cost DOUBLE DEFAULT 0.0,
        market_value DOUBLE DEFAULT 0.0,
        unrealized_pnl DOUBLE DEFAULT 0.0,
        frozen INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS position_snapshots (
        date DATE NOT NULL,
        ticker VARCHAR NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        quantity INTEGER NOT NULL,
        avg_cost DOUBLE NOT NULL,
        close_price DOUBLE NOT NULL,
        market_value DOUBLE NOT NULL,
        PRIMARY KEY (date, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        ticker VARCHAR NOT NULL,
        event_date DATE NOT NULL,
        event_type VARCHAR NOT NULL,
        cash_per_share DOUBLE DEFAULT 0.0,
        bonus_ratio DOUBLE DEFAULT 0.0,
        split_ratio DOUBLE DEFAULT 1.0,
        PRIMARY KEY (ticker, event_date, event_type)
    )
    """,
]


def init_schema(engine: DuckDBEngine) -> None:
    for ddl in _TABLES:
        engine.execute(ddl)

    existing = engine.query_df("SELECT COUNT(*) AS c FROM schema_version")
    if existing["c"][0] == 0:
        engine.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            [SCHEMA_VERSION],
        )


def migrate(engine: DuckDBEngine) -> None:
    row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = row["v"][0] or 0
    if current < SCHEMA_VERSION:
        init_schema(engine)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_store_schema.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/store/schema.py tests/unit/test_store_schema.py
git commit -m "feat: DuckDB schema with versioned table migrations"
```

---

### Task 10: Data Store Repository

**Files:**
- Create: `FisherQuant/fisher/store/repository.py`
- Create: `FisherQuant/tests/unit/test_store_repository.py`

**Interfaces:**
- Consumes: `DuckDBEngine` (Task 8), schema tables (Task 9)
- Produces:
  - `BarRepo.save_bars_daily(engine, bars: polars.DataFrame) -> None`
  - `BarRepo.get_bars_daily(engine, tickers: list[str], start: str, end: str) -> polars.DataFrame`
  - `PositionRepo.save_snapshot(engine, date: str, positions: dict) -> None`
  - `PositionRepo.get_snapshots(engine, start: str, end: str) -> polars.DataFrame`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_store_repository.py
import tempfile
from pathlib import Path
import polars as pl
from datetime import date
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.store.repository import BarRepo, PositionRepo


class TestBarRepo:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = DuckDBEngine(str(Path(self.tmp.name) / "test.db"))
        init_schema(self.engine)

    def teardown_method(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_save_and_get_bars(self):
        bars = pl.DataFrame({
            "ticker": ["000001.SZ", "000001.SZ", "600036.SH"],
            "trade_date": [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 2)],
            "open": [10.0, 10.2, 30.0],
            "high": [11.0, 10.8, 31.0],
            "low": [9.8, 10.0, 29.5],
            "close": [10.5, 10.3, 30.5],
            "volume": [1000000, 1200000, 500000],
            "amount": [10500000.0, 12360000.0, 15250000.0],
            "market": ["a_share", "a_share", "a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars)

        result = BarRepo.get_bars_daily(
            self.engine,
            tickers=["000001.SZ"],
            start="2025-01-01",
            end="2025-01-05",
        )
        assert len(result) == 2
        assert result["close"].to_list() == [10.5, 10.3]

    def test_get_bars_empty_when_no_data(self):
        result = BarRepo.get_bars_daily(
            self.engine,
            tickers=["999999.SZ"],
            start="2020-01-01",
            end="2020-12-31",
        )
        assert len(result) == 0

    def test_save_bars_upserts(self):
        bars1 = pl.DataFrame({
            "ticker": ["000001.SZ"],
            "trade_date": [date(2025, 1, 2)],
            "open": [10.0], "high": [11.0], "low": [9.8], "close": [10.5],
            "volume": [1000000], "amount": [10500000.0], "market": ["a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars1)

        bars2 = pl.DataFrame({
            "ticker": ["000001.SZ"],
            "trade_date": [date(2025, 1, 2)],
            "open": [10.1], "high": [11.1], "low": [9.9], "close": [10.6],
            "volume": [1100000], "amount": [11500000.0], "market": ["a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars2)

        result = BarRepo.get_bars_daily(
            self.engine, tickers=["000001.SZ"], start="2025-01-01", end="2025-01-05"
        )
        assert len(result) == 1
        assert result["close"][0] == 10.6  # upsert updated


class TestPositionRepo:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = DuckDBEngine(str(Path(self.tmp.name) / "test.db"))
        init_schema(self.engine)

    def teardown_method(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_save_and_get_snapshots(self):
        positions = [
            {"ticker": "000001.SZ", "market": "a_share", "quantity": 100,
             "avg_cost": 10.0, "close_price": 10.5, "market_value": 1050.0},
            {"ticker": "00700.HK", "market": "hk_connect", "quantity": 200,
             "avg_cost": 300.0, "close_price": 310.0, "market_value": 62000.0},
        ]
        PositionRepo.save_snapshot(self.engine, "2025-01-02", positions)

        result = PositionRepo.get_snapshots(self.engine, "2025-01-01", "2025-01-05")
        assert len(result) == 2
        assert set(result["ticker"].to_list()) == {"000001.SZ", "00700.HK"}
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_store_repository.py -v`
Expected: all FAIL

- [ ] **Step 3: Write store/repository.py**

```python
# fisher/store/repository.py
import polars as pl
from .engine import DuckDBEngine


class BarRepo:
    @staticmethod
    def save_bars_daily(engine: DuckDBEngine, bars: pl.DataFrame) -> None:
        existing = bars.to_dicts()
        engine.execute_many(
            """INSERT OR REPLACE INTO bars_daily
               (ticker, trade_date, open, high, low, close, volume, amount, market)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                [
                    r["ticker"], r["trade_date"], r["open"], r["high"],
                    r["low"], r["close"], r["volume"], r["amount"], r["market"],
                ]
                for r in existing
            ],
        )

    @staticmethod
    def get_bars_daily(
        engine: DuckDBEngine, tickers: list[str], start: str, end: str
    ) -> pl.DataFrame:
        if not tickers:
            return pl.DataFrame()
        placeholders = ",".join(["?"] * len(tickers))
        return engine.query_df(
            f"""SELECT * FROM bars_daily
                WHERE ticker IN ({placeholders})
                  AND trade_date >= ?
                  AND trade_date <= ?
                ORDER BY ticker, trade_date""",
            [*tickers, start, end],
        )


class PositionRepo:
    @staticmethod
    def save_snapshot(
        engine: DuckDBEngine, date: str, positions: list[dict]
    ) -> None:
        if not positions:
            return
        engine.execute_many(
            """INSERT OR REPLACE INTO position_snapshots
               (date, ticker, market, quantity, avg_cost, close_price, market_value)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                [
                    date, p["ticker"], p.get("market", "a_share"),
                    p["quantity"], p["avg_cost"],
                    p["close_price"], p["market_value"],
                ]
                for p in positions
            ],
        )

    @staticmethod
    def get_snapshots(
        engine: DuckDBEngine, start: str, end: str
    ) -> pl.DataFrame:
        return engine.query_df(
            """SELECT * FROM position_snapshots
               WHERE date >= ? AND date <= ?
               ORDER BY date, ticker""",
            [start, end],
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_store_repository.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add fisher/store/repository.py tests/unit/test_store_repository.py
git commit -m "feat: data repository with BarRepo and PositionRepo"
```

---

## Next Phases

> **Note:** Per scope decomposition guidance, subsequent phases will be written as separate plan documents building on this foundation:
> - `2025-07-25-fisherquant-phase2.md` — Market Gateway + Factor Engine
> - `2025-07-25-fisherquant-phase3.md` — Strategy Engine + Portfolio Builder
> - `2025-07-25-fisherquant-phase4.md` — Paper Engine + OMS + Position + Risk
> - `2025-07-25-fisherquant-phase5.md` — Backtest Engine + Analytics
> - `2025-07-25-fisherquant-phase6.md` — Monitor + Alert + Scheduler + Auth
>
> Each phase plan produces testable, working software building on its predecessors.

---

### Self-Review

**1. Spec coverage:** Phase 1 tasks correspond to spec sections 3 (event bus), 4 (tech stack), 17 (logging), 18 (config), 19 (store). Phase 2-6 will cover remaining modules. No spec gaps for Phase 1.

**2. Placeholder scan:** All steps have concrete code. No TBD/TODO markers. Phase 2-6 is outlined but not yet detailed — this is intentional (plan focuses on Phase 1 first).

**3. Type consistency:** `AppConfig` fields match between schemas.py and loader.py. Event types in types.py match those used in bus.py tests. Store repository methods match schema table names.

**4. Missing from spec:** CLI entry point (`fisher` command) is referenced in pyproject.toml but will be implemented later when module integration tasks run.

**5. All tasks end with a commit step** — each task produces an independently working, testable unit.
