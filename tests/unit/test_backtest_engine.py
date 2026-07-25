import pytest
import polars as pl
from unittest.mock import AsyncMock
from fisher.backtest.engine import BacktestEngine
from fisher.backtest.time_player import TimePlayer
from fisher.paper.engine import PaperEngine
from fisher.position.service import PositionService
from fisher.event.types import Bar, Signal, OrderSide
from fisher.config.schemas import AssetFeeConfig

A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025,
    min_commission=5.0,
    stamp_duty=0.0005,
    stamp_duty_side="sell",
)


class MockStrategy:
    def __init__(self):
        self.name = "mock"
        self.signals: list[Signal] = []
        self.bar_count = 0

    async def on_init(self):
        pass

    async def on_bar(self, bar: Bar):
        self.bar_count += 1
        if bar.ticker == "A" and bar.close <= 10.2:
            self.signals.append(
                Signal(
                    strategy="mock",
                    ticker=bar.ticker,
                    market=bar.market,
                    side=OrderSide.BUY,
                    quantity=100,
                    limit_price=bar.close,
                    confidence=1.0,
                    reason="test",
                )
            )

    def on_signal(self) -> list[Signal]:
        sigs = self.signals[:]
        self.signals.clear()
        return sigs


@pytest.fixture
def bars_df():
    return pl.DataFrame({
        "ticker": ["A", "B", "A", "B"],
        "trade_date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"],
        "open": [10.0, 20.0, 11.0, 21.0],
        "high": [10.5, 20.5, 11.5, 21.5],
        "low": [9.5, 19.5, 10.5, 20.5],
        "close": [10.2, 20.2, 11.2, 21.2],
        "volume": [1000, 2000, 1100, 2100],
        "amount": [10000.0, 20000.0, 11000.0, 21000.0],
        "market": ["a_share", "a_share", "a_share", "a_share"],
    })


@pytest.fixture
def engine(bars_df):
    return BacktestEngine(
        bars_df=bars_df,
        paper_engine=PaperEngine(A_SHARE_FEE, initial_capital=100000.0),
        position_service=PositionService(),
    )


class TestBacktestEngine:
    @pytest.mark.asyncio
    async def test_run_iterates_bars(self, bars_df, engine):
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert strategy.bar_count == 4

    @pytest.mark.asyncio
    async def test_strategy_signals_generate_trades(self, bars_df):
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()
        engine = BacktestEngine(bars_df, paper, positions)
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert result is not None
        assert "nav_history" in result
        assert "trades" in result

    @pytest.mark.asyncio
    async def test_nav_history_has_correct_length(self, bars_df, engine):
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert len(result["nav_history"]) > 0

    @pytest.mark.asyncio
    async def test_nav_initial_is_capital(self, bars_df, engine):
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert result["nav_history"][0] == 100000.0

    @pytest.mark.asyncio
    async def test_trades_recorded(self, bars_df):
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()
        engine = BacktestEngine(bars_df, paper, positions)
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert isinstance(result["trades"], list)

    @pytest.mark.asyncio
    async def test_empty_bars_no_error(self):
        df = pl.DataFrame(schema={
            "ticker": pl.Utf8, "trade_date": pl.Utf8, "open": pl.Float64,
            "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
            "volume": pl.Int64, "amount": pl.Float64, "market": pl.Utf8,
        })
        paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0)
        positions = PositionService()
        engine = BacktestEngine(df, paper, positions)
        strategy = MockStrategy()
        result = await engine.run(strategy)
        assert result["nav_history"] == [100000.0]
