import asyncio
import time
import pytest
import polars as pl
from tests.factories import DataFactory


class TestDataGenerationPerformance:
    def test_generate_1y_data(self):
        factory = DataFactory(seed=42)
        start = time.perf_counter()
        df = factory.generate_ohlcv("TEST.SZ", days=252, trend="random")
        elapsed = time.perf_counter() - start
        assert len(df) == 252
        assert elapsed < 1.0, f"Data generation too slow: {elapsed:.2f}s"

    def test_generate_10_symbols(self):
        factory = DataFactory(seed=42)
        start = time.perf_counter()
        for i in range(10):
            factory.generate_ohlcv(f"TEST{i:03d}.SZ", days=252, trend="random")
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"10-symbol generation too slow: {elapsed:.2f}s"


class TestBacktestPerformance:
    @pytest.mark.slow
    def test_single_strategy_1y(self):
        factory = DataFactory(seed=42)
        df = factory.generate_ohlcv("TEST.SZ", days=252, trend="random")

        start = time.perf_counter()
        result = asyncio.run(_run_backtest_single(df))
        elapsed = time.perf_counter() - start
        assert len(result["nav_history"]) > 0
        assert elapsed <= 5.0, f"Single strategy/1y too slow: {elapsed:.2f}s"

    @pytest.mark.slow
    def test_10_symbols_1y(self):
        factory = DataFactory(seed=42)
        dfs = []
        for i in range(10):
            dfs.append(factory.generate_ohlcv(f"TEST{i:03d}.SZ", days=252, trend="random"))
        combined = pl.concat(dfs).sort(["trade_date", "ticker"])

        start = time.perf_counter()
        result = asyncio.run(_run_backtest_single(combined))
        elapsed = time.perf_counter() - start
        assert len(result["nav_history"]) > 0
        assert elapsed <= 30.0, f"10 symbols/1y too slow: {elapsed:.2f}s"

    @pytest.mark.slow
    def test_walk_forward_3y(self):
        factory = DataFactory(seed=42)
        df = factory.generate_ohlcv("TEST.SZ", days=756, trend="random")

        start = time.perf_counter()
        result = asyncio.run(_run_backtest_single(df))
        elapsed = time.perf_counter() - start
        assert len(result["nav_history"]) > 0
        assert elapsed <= 45.0, f"Walk-forward/3y too slow: {elapsed:.2f}s"

    @pytest.mark.slow
    def test_parameter_sensitivity(self):
        factory = DataFactory(seed=42)
        df = factory.generate_ohlcv("TEST.SZ", days=252, trend="random")

        fast_params = list(range(5, 55, 10))
        slow_params = list(range(20, 70, 10))

        start = time.perf_counter()
        for fast in fast_params:
            for slow in slow_params:
                if fast >= slow:
                    continue
                asyncio.run(_run_backtest_single(df.clone()))
        elapsed = time.perf_counter() - start
        assert elapsed <= 60.0, f"Parameter sensitivity too slow: {elapsed:.2f}s"


async def _run_backtest_single(bars_df):
    from fisher.backtest.engine import BacktestEngine
    from fisher.paper.engine import PaperEngine
    from fisher.position.service import PositionService
    from fisher.config.schemas import AssetFeeConfig

    fee = AssetFeeConfig(
        commission_rate=0.00025,
        min_commission=5.0,
        stamp_duty=0.0005,
        stamp_duty_side="sell",
    )
    paper = PaperEngine(fee, initial_capital=100000.0)
    positions = PositionService()
    engine = BacktestEngine(bars_df, paper, positions)

    from fisher.event.types import Bar, Signal, OrderSide

    class SimpleStrategy:
        def __init__(self):
            self.name = "simple"
            self._signals: list = []
            self._bar_count = 0

        async def on_init(self):
            pass

        async def on_bar(self, bar):
            self._bar_count += 1
            if self._bar_count > 5 and bar.ticker == bars_df["ticker"][0]:
                if bar.close < 110.0:
                    self._signals.append(
                        Signal(
                            strategy="simple",
                            ticker=bar.ticker,
                            market=bar.market,
                            side=OrderSide.BUY,
                            quantity=100,
                            limit_price=bar.close,
                            confidence=1.0,
                            reason="benchmark",
                        )
                    )

        def on_signal(self):
            sigs = self._signals[:]
            self._signals.clear()
            return sigs

    result = await engine.run(SimpleStrategy())
    return result
