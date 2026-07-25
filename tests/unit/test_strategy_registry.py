import pytest
from fisher.event.types import Bar, OrderSide
from fisher.strategy.base import Strategy
from fisher.strategy.registry import StrategyRegistry
from fisher.strategy.engine import StrategyEngine


class _TestStrat(Strategy):
    name = "test_strategy"
    bars_received: list[Bar]

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.bars_received = []

    async def on_bar(self, bar: Bar):
        self.bars_received.append(bar)


class _AnotherStrat(Strategy):
    name = "another_strategy"
    bars_received: list[Bar]

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.bars_received = []

    async def on_bar(self, bar: Bar):
        self.bars_received.append(bar)


class TestStrategyRegistry:
    def setup_method(self):
        StrategyRegistry.clear()

    def test_register_and_get(self):
        StrategyRegistry.register(_TestStrat)
        cls = StrategyRegistry.get("test_strategy")
        assert cls is _TestStrat

    def test_list_all(self):
        StrategyRegistry.register(_TestStrat)
        StrategyRegistry.register(_AnotherStrat)
        names = StrategyRegistry.list_all()
        assert "test_strategy" in names
        assert "another_strategy" in names
        assert len(names) == 2

    def test_get_missing_raises(self):
        with pytest.raises(KeyError, match="not registered"):
            StrategyRegistry.get("nonexistent")

    def test_clear(self):
        StrategyRegistry.register(_TestStrat)
        StrategyRegistry.clear()
        assert StrategyRegistry.list_all() == []


class TestStrategyEngine:
    def setup_method(self):
        StrategyRegistry.clear()
        StrategyRegistry.register(_TestStrat)

    def test_load_creates_instance(self):
        engine = StrategyEngine()
        s = engine.load("test_strategy", {"param1": 42})
        assert isinstance(s, _TestStrat)
        assert s.params["param1"] == 42

    def test_load_unknown_strategy_raises(self):
        engine = StrategyEngine()
        with pytest.raises(KeyError):
            engine.load("nonexistent")

    def test_on_bar_dispatches_to_all(self):
        engine = StrategyEngine()
        StrategyRegistry.register(_AnotherStrat)
        s1 = engine.load("test_strategy")
        s2 = engine.load("another_strategy")
        bar = Bar(ticker="000001.SZ", open=10.0, high=11.0, low=9.5, close=10.5, volume=1000, amount=10500.0)
        import asyncio
        asyncio.run(engine.on_bar(bar))
        assert len(s1.bars_received) == 1
        assert len(s2.bars_received) == 1

    def test_collect_signals(self):
        engine = StrategyEngine()
        s = engine.load("test_strategy")
        s.emit_signal("000001.SZ", "a_share", OrderSide.BUY, 100)
        s.emit_signal("000002.SZ", "a_share", OrderSide.SELL, 50)
        signals = engine.collect_signals()
        assert len(signals) == 2

    def test_pause_and_resume(self):
        engine = StrategyEngine()
        StrategyRegistry.register(_AnotherStrat)
        s1 = engine.load("test_strategy")
        s2 = engine.load("another_strategy")

        engine.pause("test_strategy")
        assert engine.is_paused("test_strategy")

        bar = Bar(ticker="000001.SZ", open=10.0, high=11.0, low=9.5, close=10.5, volume=1000, amount=10500.0)
        import asyncio
        asyncio.run(engine.on_bar(bar))

        assert len(s1.bars_received) == 0
        assert len(s2.bars_received) == 1

        engine.resume("test_strategy")
        assert not engine.is_paused("test_strategy")

        asyncio.run(engine.on_bar(bar))
        assert len(s1.bars_received) == 1
        assert len(s2.bars_received) == 2

    def test_pause_unknown_does_nothing(self):
        engine = StrategyEngine()
        engine.pause("nonexistent")

    def test_collect_signals_skips_paused(self):
        engine = StrategyEngine()
        s = engine.load("test_strategy")
        s.emit_signal("000001.SZ", "a_share", OrderSide.BUY, 100)
        engine.pause("test_strategy")
        signals = engine.collect_signals()
        assert len(signals) == 0

    def test_list_loaded(self):
        engine = StrategyEngine()
        engine.load("test_strategy")
        StrategyRegistry.register(_AnotherStrat)
        engine.load("another_strategy")
        loaded = engine.list_loaded()
        assert "test_strategy" in loaded
        assert "another_strategy" in loaded
        assert len(loaded) == 2
