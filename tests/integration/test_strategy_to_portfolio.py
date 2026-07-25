import pytest
import asyncio
from fisher.event.types import Bar, OrderSide, OrderPending
from fisher.strategy.builtin.momentum import MomentumStrategy
from fisher.strategy.engine import StrategyEngine
from fisher.strategy.registry import StrategyRegistry
from fisher.portfolio.builder import PortfolioBuilder


def _make_bar(ticker="000001.SZ", close=10.0, market="a_share"):
    return Bar(
        ticker=ticker,
        market=market,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=close * 10000,
    )


class TestStrategyToPortfolioPipeline:
    def setup_method(self):
        StrategyRegistry.clear()
        self._engine = StrategyEngine()

    def test_momentum_to_portfolio_e2e(self):
        StrategyRegistry.register(MomentumStrategy)
        s = self._engine.load("momentum", {"fast_window": 3, "slow_window": 5})

        closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5, 11.0, 12.0, 13.0, 14.0]
        for c in closes:
            bar = _make_bar(ticker="000001.SZ", close=c)
            asyncio.run(s.on_bar(bar))

        signals = s.on_signal()
        assert len(signals) > 0, "Should produce at least one signal"

        builder = PortfolioBuilder(method="equal_weight", max_positions=20)
        orders = builder.build_orders(signals, capital=1_000_000)

        assert len(orders) > 0, "Should produce at least one order"
        for o in orders:
            assert isinstance(o, OrderPending)
            assert o.ticker == "000001.SZ"
            assert o.price > 0

    def test_multi_strategy_to_portfolio(self):
        from fisher.strategy.builtin.mean_reversion import MeanReversionStrategy

        StrategyRegistry.register(MomentumStrategy)
        StrategyRegistry.register(MeanReversionStrategy)

        m = self._engine.load("momentum", {"fast_window": 3, "slow_window": 5})
        r = self._engine.load("mean_reversion", {"window": 5, "std_mult": 1.5})

        closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.5, 11.0, 12.0, 13.0, 14.0]
        for c in closes:
            bar = _make_bar(ticker="000001.SZ", close=c)
            asyncio.run(self._engine.on_bar(bar))

        signals = self._engine.collect_signals()
        assert len(signals) > 0, "Multi-strategy should produce signals"

        builder = PortfolioBuilder(method="equal_weight", max_positions=10)
        orders = builder.build_orders(signals, capital=1_000_000)

        assert len(orders) > 0
        for o in orders:
            assert isinstance(o, OrderPending)

    def test_pipeline_to_portfolio_integration(self):
        from fisher.strategy.pipeline import parse_pipeline_yaml
        import tempfile
        import os

        yaml_content = """
pipeline:
  universe: csi300
  lookback: 252d
  factors: [momentum_20d, volatility_60d]
  model:
    type: linear
    weights: [0.6, 0.4]
  portfolio:
    top_k: 30
    method: equal_weight
"""
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, encoding="utf-8"
            ) as f:
                f.write(yaml_content)
                tmp = f.name

            config = parse_pipeline_yaml(tmp)
            assert config.universe == "csi300"
            assert config.portfolio.top_k == 30
            assert config.portfolio.method == "equal_weight"

            from fisher.strategy.pipeline import build_strategy_from_pipeline
            strategy = build_strategy_from_pipeline(config)
            strategy.set_factor_scores({"A": 0.9, "B": 0.8, "C": 0.5, "D": 0.3})
            strategy.generate_signals()
            signals = strategy.on_signal()

            assert len(signals) > 0

            builder = PortfolioBuilder(
                method=config.portfolio.method,
                max_positions=config.portfolio.top_k,
            )
            orders = builder.build_orders(signals, capital=1_000_000)
            assert len(orders) > 0
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def test_conflict_resolution_in_pipeline(self):
        signals = [
            pytest.importorskip("fisher.event.types").Signal(
                strategy="s1", ticker="A", market="a_share",
                side=OrderSide.BUY, quantity=100, confidence=0.8, reason="test",
            ),
            pytest.importorskip("fisher.event.types").Signal(
                strategy="s2", ticker="A", market="a_share",
                side=OrderSide.SELL, quantity=50, confidence=0.6, reason="test",
            ),
        ]

        builder_skip = PortfolioBuilder(conflict_mode="skip_conflict")
        assert len(builder_skip.build_orders(signals, 100000)) == 0

        builder_merge = PortfolioBuilder(conflict_mode="weighted_merge")
        assert len(builder_merge.build_orders(signals, 100000)) == 1

        builder_first = PortfolioBuilder(conflict_mode="first_wins")
        orders = builder_first.build_orders(signals, 100000)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY
