from enum import Enum
from typing import Any, Optional
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
    params: dict[str, Any] = {}


class RealtimeRiskConfig(BaseModel):
    var_confidence: float = 0.99
    max_drawdown: float = 0.15
    beta_limit: float = 1.5


class RiskConfig(BaseModel):
    pre_trade: list[PreTradeRuleConfig] = [
        PreTradeRuleConfig(rule="MaxPosition", params={"max_pct": 0.15}),
        PreTradeRuleConfig(rule="DailyLossLimit", params={"max_loss_pct": 0.03}),
        PreTradeRuleConfig(rule="PriceLimit", params={"upper": 0.095, "lower": -0.095}),
    ]
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
    assets: dict[str, AssetFeeConfig] = {
        "a_share": AssetFeeConfig(
            commission_rate=0.00025,
            min_commission=5.0,
            stamp_duty=0.0005,
            stamp_duty_side="sell",
        ),
        "etf": AssetFeeConfig(commission_rate=0.00025, min_commission=5.0),
        "convertible_bond": AssetFeeConfig(commission_rate=0.00025),
        "hk_connect": AssetFeeConfig(commission_rate=0.0003, min_commission=3.0),
    }


class AlertChannelConfig(BaseModel):
    type: str = "console"
    webhook: Optional[str] = None
    events: list[str] = []
    level: str = "INFO"
    throttle: int = 60


class AlertConfig(BaseModel):
    channels: dict[str, AlertChannelConfig] = {
        "console": AlertChannelConfig(type="console", events=["order", "risk", "system"]),
    }


class BenchmarkItem(BaseModel):
    name: str
    ticker: str
    weight: float = 1.0


class BenchmarkConfig(BaseModel):
    benchmarks: list[BenchmarkItem] = [BenchmarkItem(name="CSI300", ticker="000300.SH")]


class BrokerConfig(BaseModel):
    name: str = "paper"
    params: dict[str, Any] = {}


class AppConfig(BaseModel):
    system: SystemConfig = SystemConfig()
    market: MarketConfig = MarketConfig()
    strategy: StrategyConfig = StrategyConfig()
    risk: RiskConfig = RiskConfig()
    fees: FeesConfig = FeesConfig()
    alert: AlertConfig = AlertConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()
    broker: BrokerConfig = BrokerConfig()
