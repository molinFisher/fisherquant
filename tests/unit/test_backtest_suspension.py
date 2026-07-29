"""G2 可交易状态校验：停牌期跳过信号 + SuspensionService 数据层。"""
import pytest
import polars as pl
from fisher.backtest.engine import BacktestEngine
from fisher.paper.engine import PaperEngine
from fisher.position.service import PositionService
from fisher.event.types import Bar, Signal, OrderSide
from fisher.config.schemas import AssetFeeConfig
from fisher.market.suspension import SuspensionService

A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025, min_commission=5.0,
    stamp_duty=0.0005, stamp_duty_side="sell",
)


class SuspendStrategy:
    def __init__(self):
        self.name = "suspend"
        self.signals: list[Signal] = []

    async def on_init(self):
        pass

    async def on_bar(self, bar: Bar):
        # 两个交易日都发出买入信号，便于对照"跳过 vs 成交"
        if bar.ticker == "A" and bar.close <= 12.0:
            self.signals.append(Signal(
                strategy="suspend", ticker=bar.ticker, market=bar.market,
                side=OrderSide.BUY, quantity=100, limit_price=bar.close,
            ))

    def on_signal(self):
        sigs = self.signals[:]
        self.signals.clear()
        return sigs


@pytest.fixture
def bars_df():
    # 3 根 bar：成交延迟 1 根，故首日信号在第 2 根成交、次日信号在第 3 根成交
    return pl.DataFrame({
        "ticker": ["A", "A", "A"],
        "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "open": [10.0, 11.0, 12.0],
        "high": [10.5, 11.5, 12.5],
        "low": [9.5, 10.5, 11.5],
        "close": [10.2, 11.2, 12.2],
        "volume": [1000, 1100, 1200],
        "amount": [10000.0, 11000.0, 12000.0],
        "market": ["a_share", "a_share", "a_share"],
    })


@pytest.mark.asyncio
async def test_suspended_signal_skipped_and_counted(bars_df):
    svc = SuspensionService()
    svc.add_suspension("A", "2024-01-01")
    paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0, slippage_bps=0.0)
    engine = BacktestEngine(
        bars_df, paper, PositionService(),
        suspension_provider=lambda t, d: svc.is_suspended(t, d),
    )
    result = await engine.run(SuspendStrategy())
    # 2024-01-01 停牌 → 跳过 1 次；2024-01-02 信号在 01-03 成交
    assert result["skipped_signals"] == 1
    a_trades = [t for t in result["trades"] if t["ticker"] == "A"]
    assert len(a_trades) == 1
    assert a_trades[0]["trade_date"] == "2024-01-03"


@pytest.mark.asyncio
async def test_no_provider_runs_unchanged(bars_df):
    paper = PaperEngine(A_SHARE_FEE, initial_capital=100000.0, slippage_bps=0.0)
    engine = BacktestEngine(bars_df, paper, PositionService())  # 无 provider
    result = await engine.run(SuspendStrategy())
    assert result["skipped_signals"] == 0
    assert len([t for t in result["trades"] if t["ticker"] == "A"]) == 2


def test_suspension_service_range():
    svc = SuspensionService()
    svc.add_suspension_range("600519.SH", "2024-03-01", "2024-03-03")
    assert svc.is_suspended("600519.SH", "2024-03-01") is True
    assert svc.is_suspended("600519.SH", "2024-03-02") is True
    assert svc.is_suspended("600519.SH", "2024-03-03") is True
    assert svc.is_suspended("600519.SH", "2024-03-04") is False
