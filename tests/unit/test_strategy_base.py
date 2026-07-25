import pytest
from fisher.event.types import Bar, OrderFilled, OrderSide
from fisher.strategy.base import Strategy


class ConcreteStrategy(Strategy):
    name = "concrete"
    bars_received: list[Bar]

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        self.bars_received = []

    async def on_bar(self, bar: Bar):
        self.bars_received.append(bar)


class TestStrategyLifecycle:
    def test_on_init_called(self):
        s = ConcreteStrategy()
        import asyncio
        asyncio.run(s.on_init())

    def test_on_bar_called(self):
        s = ConcreteStrategy()
        bar = Bar(ticker="000001.SZ", open=10.0, high=11.0, low=9.5, close=10.5, volume=1000, amount=10500.0)
        import asyncio
        asyncio.run(s.on_bar(bar))
        assert len(s.bars_received) == 1
        assert s.bars_received[0].ticker == "000001.SZ"

    def test_on_signal_collects_and_clears(self):
        s = ConcreteStrategy()
        s.emit_signal("000001.SZ", "a_share", OrderSide.BUY, 100, 10.5, 0.8, "test")
        s.emit_signal("000002.SZ", "a_share", OrderSide.SELL, 50, 20.0, 0.6, "test2")
        signals = s.on_signal()
        assert len(signals) == 2
        assert signals[0].ticker == "000001.SZ"
        assert signals[1].ticker == "000002.SZ"
        assert len(s.on_signal()) == 0


class TestStrategyState:
    def test_serialize_state(self):
        s = ConcreteStrategy({"lookback": 20})
        state = s.serialize_state()
        assert state["params"] == {"lookback": 20}

    def test_restore_state(self):
        s = ConcreteStrategy({"lookback": 10})
        s.restore_state({"params": {"lookback": 30}})
        assert s.params["lookback"] == 30

    def test_restore_state_defaults_missing_params(self):
        s = ConcreteStrategy({"lookback": 10})
        s.restore_state({})
        assert s.params == {}


class TestStrategySignalEmission:
    def test_emit_signal_creates_signal(self):
        s = ConcreteStrategy()
        s.emit_signal("000001.SZ", "a_share", OrderSide.BUY, 100, 10.5, 0.8, "ma_cross")
        signals = s.on_signal()
        assert len(signals) == 1
        sig = signals[0]
        assert sig.strategy == "concrete"
        assert sig.ticker == "000001.SZ"
        assert sig.market == "a_share"
        assert sig.side == OrderSide.BUY
        assert sig.quantity == 100
        assert sig.limit_price == 10.5
        assert sig.confidence == 0.8
        assert sig.reason == "ma_cross"

    def test_emit_signal_default_values(self):
        s = ConcreteStrategy()
        s.emit_signal("000001.SZ", "a_share", OrderSide.SELL, 50)
        signals = s.on_signal()
        assert signals[0].limit_price == 0.0
        assert signals[0].confidence == 1.0
        assert signals[0].reason == ""


class TestStrategyParams:
    def test_default_params(self):
        s = ConcreteStrategy()
        assert s.params == {}

    def test_custom_params(self):
        s = ConcreteStrategy({"period": 14, "threshold": 0.05})
        assert s.params["period"] == 14
        assert s.params["threshold"] == 0.05
