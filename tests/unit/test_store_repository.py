import tempfile
from pathlib import Path
import polars as pl
from datetime import date
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.store.repository import BarRepo, PositionRepo


class TestBarRepo:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = DuckDBEngine(str(Path(self.tmp.name) / "test.db"))
        init_schema(self.engine)

    def teardown_method(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_save_and_get_bars(self):
        bars = pl.DataFrame({
            "ticker": ["000001.SZ", "000001.SZ", "600036.SH"],
            "trade_date": [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 2)],
            "open": [10.0, 10.2, 30.0],
            "high": [11.0, 10.8, 31.0],
            "low": [9.8, 10.0, 29.5],
            "close": [10.5, 10.3, 30.5],
            "volume": [1000000, 1200000, 500000],
            "amount": [10500000.0, 12360000.0, 15250000.0],
            "market": ["a_share", "a_share", "a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars)

        result = BarRepo.get_bars_daily(
            self.engine,
            tickers=["000001.SZ"],
            start="2025-01-01",
            end="2025-01-05",
        )
        assert len(result) == 2
        assert result["close"].to_list() == [10.5, 10.3]

    def test_get_bars_empty_when_no_data(self):
        result = BarRepo.get_bars_daily(
            self.engine,
            tickers=["999999.SZ"],
            start="2020-01-01",
            end="2020-12-31",
        )
        assert len(result) == 0

    def test_save_bars_upserts(self):
        bars1 = pl.DataFrame({
            "ticker": ["000001.SZ"],
            "trade_date": [date(2025, 1, 2)],
            "open": [10.0], "high": [11.0], "low": [9.8], "close": [10.5],
            "volume": [1000000], "amount": [10500000.0], "market": ["a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars1)

        bars2 = pl.DataFrame({
            "ticker": ["000001.SZ"],
            "trade_date": [date(2025, 1, 2)],
            "open": [10.1], "high": [11.1], "low": [9.9], "close": [10.6],
            "volume": [1100000], "amount": [11500000.0], "market": ["a_share"],
        })
        BarRepo.save_bars_daily(self.engine, bars2)

        result = BarRepo.get_bars_daily(
            self.engine, tickers=["000001.SZ"], start="2025-01-01", end="2025-01-05"
        )
        assert len(result) == 1
        assert result["close"][0] == 10.6


class TestPositionRepo:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = DuckDBEngine(str(Path(self.tmp.name) / "test.db"))
        init_schema(self.engine)

    def teardown_method(self):
        self.engine.close()
        self.tmp.cleanup()

    def test_save_and_get_snapshots(self):
        positions = [
            {"ticker": "000001.SZ", "market": "a_share", "quantity": 100,
             "avg_cost": 10.0, "close_price": 10.5, "market_value": 1050.0},
            {"ticker": "00700.HK", "market": "hk_connect", "quantity": 200,
             "avg_cost": 300.0, "close_price": 310.0, "market_value": 62000.0},
        ]
        PositionRepo.save_snapshot(self.engine, "2025-01-02", positions)

        result = PositionRepo.get_snapshots(self.engine, "2025-01-01", "2025-01-05")
        assert len(result) == 2
        assert set(result["ticker"].to_list()) == {"000001.SZ", "00700.HK"}
