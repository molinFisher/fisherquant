"""G4 沙盒对账 + 合规日志 单测。"""
import pytest
import polars as pl
from fisher.backtest.engine import BacktestEngine
from fisher.paper.engine import PaperEngine
from fisher.paper.reconcile import reconcile, daily_settle, Discrepancy
from fisher.position.service import PositionService
from fisher.risk.audit import AuditLogger
from fisher.event.types import Bar, Signal, OrderSide
from fisher.config.schemas import AssetFeeConfig

A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025, min_commission=5.0,
    stamp_duty=0.0005, stamp_duty_side="sell",
)


class AuditStrategy:
    def __init__(self):
        self.name = "audit"
        self.signals: list[Signal] = []

    async def on_init(self):
        pass

    async def on_bar(self, bar: Bar):
        if bar.ticker == "A" and bar.close <= 12.0:
            self.signals.append(Signal(
                strategy="audit", ticker=bar.ticker, market=bar.market,
                side=OrderSide.BUY, quantity=100, limit_price=bar.close))

    def on_signal(self):
        s = self.signals[:]
        self.signals.clear()
        return s


@pytest.fixture
def bars_df():
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


def test_reconcile_clean_no_discrepancy():
    fills = [
        {"ticker": "A", "side": "buy", "quantity": 100, "price": 11.2, "commission": 5.0},
    ]
    disc = reconcile(fills, reported_cash=1_000_000 - 11.2 * 100 - 5.0,
                     reported_positions={"A": {"quantity": 100}}, initial_cash=1_000_000.0)
    assert disc == []


def test_reconcile_detects_cash_mismatch():
    fills = [{"ticker": "A", "side": "buy", "quantity": 100, "price": 11.2, "commission": 5.0}]
    # 报告现金故意写错
    disc = reconcile(fills, reported_cash=999_000.0,
                     reported_positions={"A": {"quantity": 100}}, initial_cash=1_000_000.0)
    assert len(disc) == 1
    assert disc[0].field == "cash"
    assert "现金" in disc[0].detail


def test_reconcile_detects_position_mismatch():
    fills = [{"ticker": "A", "side": "buy", "quantity": 100, "price": 11.2, "commission": 5.0}]
    disc = reconcile(fills, reported_cash=1_000_000 - 11.2 * 100 - 5.0,
                     reported_positions={"A": {"quantity": 50}}, initial_cash=1_000_000.0)
    assert any(d.field == "position.A.quantity" for d in disc)


def test_daily_settle_structure():
    res = daily_settle(
        account={"available": 998_875.0},
        positions={"A": {"quantity": 100, "market_value": 1_220.0}},
        fills=[{"ticker": "A", "side": "buy", "quantity": 100, "price": 11.2, "commission": 5.0}],
        initial_cash=1_000_000.0,
    )
    assert "snapshot" in res and "discrepancies" in res
    assert res["discrepancies"] == []


@pytest.mark.asyncio
async def test_engine_audit_logger_records_events(bars_df):
    audit = AuditLogger()
    paper = PaperEngine(A_SHARE_FEE, initial_capital=1_000_000.0, slippage_bps=0.0)
    engine = BacktestEngine(bars_df, paper, PositionService(), audit_logger=audit)
    await engine.run(AuditStrategy())
    submitted = audit.query("order_submitted")
    filled = audit.query("order_filled")
    assert len(submitted) >= 1
    assert len(filled) >= 1
    # 字段完整性
    assert all("ticker" in r and "side" in r and "quantity" in r for r in submitted + filled)


@pytest.mark.asyncio
async def test_engine_no_audit_logger_default_noop(bars_df):
    # 默认不传 audit_logger 不应报错
    paper = PaperEngine(A_SHARE_FEE, initial_capital=1_000_000.0, slippage_bps=0.0)
    engine = BacktestEngine(bars_df, paper, PositionService())
    result = await engine.run(AuditStrategy())
    assert result is not None
