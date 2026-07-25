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
