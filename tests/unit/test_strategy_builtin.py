import pytest
import asyncio
from fisher.event.types import Bar, OrderSide
from fisher.strategy.builtin.momentum import MomentumStrategy
from fisher.strategy.builtin.mean_reversion import MeanReversionStrategy
from fisher.strategy.builtin.alpha_model import AlphaModelStrategy
from fisher.strategy.builtin.rotational import RotationalStrategy
from fisher.strategy.builtin.pair_trade import PairTradeStrategy
from fisher.strategy.builtin.composite import CompositeStrategy
from fisher.strategy.base import Strategy


def _make_bar(ticker="000001.SZ", close=10.0, market="a_share"):
    return Bar(
        ticker=ticker, market=market, open=close, high=close,
        low=close, close=close, volume=1000, amount=close * 10000,
    )


def _feed_bars(strategy: Strategy, ticker: str, closes: list[float]):
    for c in closes:
        asyncio.run(strategy.on_bar(_make_bar(ticker=ticker, close=c)))


class TestMomentumStrategy:
    def test_golden_cross_emits_buy(self):
        s = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5, 11.0, 12.0, 13.0, 14.0]
        _feed_bars(s, "000001.SZ", closes)
        signals = s.on_signal()
        assert any(sig.side == OrderSide.BUY for sig in signals)

    def test_death_cross_emits_sell(self):
        s = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        closes = [15.0, 14.5, 14.0, 13.5, 13.0, 12.5, 15.0, 12.0, 11.5, 11.0]
        _feed_bars(s, "000001.SZ", closes)
        signals = s.on_signal()
        assert any(sig.side == OrderSide.SELL for sig in signals)

    def test_no_signal_with_insufficient_data(self):
        s = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        _feed_bars(s, "000001.SZ", [10.0, 10.1, 10.2, 10.3])
        signals = s.on_signal()
        assert len(signals) == 0

    def test_custom_windows(self):
        s = MomentumStrategy({"fast_window": 5, "slow_window": 10})
        assert s._fast_window == 5
        assert s._slow_window == 10


class TestMeanReversionStrategy:
    def test_oversold_emits_buy(self):
        s = MeanReversionStrategy({"window": 5, "std_mult": 1.5})
        closes = [10.0, 10.1, 10.0, 9.9, 10.0, 8.0]
        _feed_bars(s, "000001.SZ", closes)
        signals = s.on_signal()
        assert any(sig.side == OrderSide.BUY for sig in signals)

    def test_overbought_emits_sell(self):
        s = MeanReversionStrategy({"window": 5, "std_mult": 1.5})
        closes = [10.0, 10.1, 10.0, 9.9, 10.0, 13.0]
        _feed_bars(s, "000001.SZ", closes)
        signals = s.on_signal()
        assert any(sig.side == OrderSide.SELL for sig in signals)

    def test_no_signal_with_insufficient_data(self):
        s = MeanReversionStrategy({"window": 20})
        _feed_bars(s, "000001.SZ", [10.0] * 10)
        signals = s.on_signal()
        assert len(signals) == 0

    def test_custom_std_mult(self):
        s = MeanReversionStrategy({"window": 5, "std_mult": 3.0})
        assert s._std_mult == 3.0


class TestAlphaModelStrategy:
    def test_top_n_emit_buy(self):
        s = AlphaModelStrategy({"top_n": 2})
        s.set_factor_scores({"A": 0.9, "B": 0.8, "C": 0.3, "D": 0.1})
        s.generate_signals()
        signals = s.on_signal()
        buy_signals = [sig for sig in signals if sig.side == OrderSide.BUY]
        assert len(buy_signals) == 2

    def test_bottom_n_emit_sell(self):
        s = AlphaModelStrategy({"top_n": 2})
        s.set_factor_scores({"A": 0.9, "B": 0.8, "C": 0.3, "D": 0.1})
        s.generate_signals()
        signals = s.on_signal()
        sell_signals = [sig for sig in signals if sig.side == OrderSide.SELL]
        assert len(sell_signals) == 2

    def test_confidence_capped_at_one(self):
        s = AlphaModelStrategy({"top_n": 1})
        s.set_factor_scores({"A": 5.0})
        s.generate_signals()
        signals = s.on_signal()
        assert signals[0].confidence <= 1.0

    def test_on_bar_noop(self):
        s = AlphaModelStrategy()
        bar = _make_bar()
        asyncio.run(s.on_bar(bar))


class TestRotationalStrategy:
    def test_emits_buy_for_top_performers(self):
        s = RotationalStrategy({"top_n": 2, "lookback": 5})
        _feed_bars(s, "A", [10.0, 10.1, 10.2, 10.5, 11.0])
        _feed_bars(s, "B", [10.0, 9.9, 9.8, 9.7, 9.5])
        _feed_bars(s, "C", [10.0, 10.05, 10.1, 10.15, 10.2])
        s.generate_signals()
        signals = s.on_signal()
        assert len(signals) == 2

    def test_no_signal_insufficient_data(self):
        s = RotationalStrategy({"top_n": 2, "lookback": 20})
        _feed_bars(s, "A", [10.0] * 10)
        s.generate_signals()
        signals = s.on_signal()
        assert len(signals) == 0

    def test_custom_top_n(self):
        s = RotationalStrategy({"top_n": 3})
        assert s._top_n == 3


class TestPairTradeStrategy:
    def test_spread_divergence_emits_signals(self):
        s = PairTradeStrategy({
            "ticker_a": "A", "ticker_b": "B",
            "window": 10, "entry_z": 1.0,
        })
        for i in range(15):
            asyncio.run(s.on_bar(_make_bar("A", close=10.0 + i * 0.01)))
            asyncio.run(s.on_bar(_make_bar("B", close=10.0 - i * 0.05)))
        signals = s.on_signal()
        assert len(signals) >= 2

    def test_no_signal_insufficient_data(self):
        s = PairTradeStrategy({"ticker_a": "A", "ticker_b": "B", "window": 30})
        for i in range(10):
            asyncio.run(s.on_bar(_make_bar("A", close=10.0)))
            asyncio.run(s.on_bar(_make_bar("B", close=10.0)))
        signals = s.on_signal()
        assert len(signals) == 0

    def test_custom_entry_z(self):
        s = PairTradeStrategy({"ticker_a": "A", "ticker_b": "B", "entry_z": 3.0})
        assert s._entry_z == 3.0


class TestCompositeStrategy:
    def test_aggregates_signals_from_children(self):
        m = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        r = MeanReversionStrategy({"window": 5, "std_mult": 1.5})
        c = CompositeStrategy()
        c.add_strategy(m)
        c.add_strategy(r)

        closes = [10.0, 10.2, 10.4, 10.6, 10.8, 11.5, 10.0, 12.0, 13.0, 14.0]
        for price in closes:
            bar = _make_bar(close=price)
            asyncio.run(c.on_bar(bar))

        signals = c.on_signal()
        assert len(signals) > 0

    def test_serialize_restore_state(self):
        m = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        c = CompositeStrategy()
        c.add_strategy(m)
        state = c.serialize_state()
        assert "strategies" in state
        assert len(state["strategies"]) == 1
        assert state["strategies"][0]["params"]["fast_window"] == 3

    def test_restore_state_applies_to_children(self):
        m = MomentumStrategy({"fast_window": 3, "slow_window": 5})
        c = CompositeStrategy()
        c.add_strategy(m)
        c.restore_state({
            "params": {},
            "strategies": [{"params": {"fast_window": 10, "slow_window": 30}}],
        })
        assert m.params["fast_window"] == 10

    def test_on_init_propagates(self):
        m = MomentumStrategy()
        c = CompositeStrategy()
        c.add_strategy(m)
        asyncio.run(c.on_init())

    def test_empty_composite_emits_no_signals(self):
        c = CompositeStrategy()
        signals = c.on_signal()
        assert len(signals) == 0
