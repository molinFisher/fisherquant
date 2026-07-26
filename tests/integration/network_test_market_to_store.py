import tempfile
import os
import pytest
import polars as pl
from fisher.market.akshare import AkshareAdapter
from fisher.config.schemas import MarketConfig
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.store.repository import BarRepo

akshare = pytest.importorskip("akshare", reason="akshare not installed")


def is_akshare_available():
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="2025-07-01", end_date="2025-07-03", adjust="qfq")
        return df is not None and not df.empty
    except Exception:
        return False


@pytest.mark.skipif(not is_akshare_available(), reason="akshare API unavailable or no network")
class TestMarketToStorePipeline:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_integration.db")
        self._db = DuckDBEngine(self._db_path)
        init_schema(self._db)
        self._gw = AkshareAdapter(MarketConfig(source="akshare"))

    def teardown_method(self):
        self._db.close()
        try:
            os.unlink(self._db_path)
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def test_fetch_and_store_single_ticker(self):
        import asyncio
        bars = asyncio.run(self._gw.get_bars("000001.SZ", "2025-07-01", "2025-07-07", "1d"))
        assert len(bars) > 0, "Should fetch at least one bar from akshare"

        bar_dicts = [b.to_dict() for b in bars]
        bars_df = pl.DataFrame(bar_dicts)

        BarRepo.save_bars_daily(self._db, bars_df)

        retrieved = BarRepo.get_bars_daily(
            self._db, ["000001.SZ"], "2025-07-01", "2025-07-07"
        )
        assert len(retrieved) > 0, "Should retrieve bars from database"

        assert retrieved["ticker"][0] == "000001.SZ"
        assert retrieved["close"].drop_nulls().len() > 0

    def test_retrieved_data_integrity(self):
        import asyncio
        bars = asyncio.run(self._gw.get_bars("000001.SZ", "2025-07-01", "2025-07-07", "1d"))
        bar_dicts = [b.to_dict() for b in bars]
        bars_df = pl.DataFrame(bar_dicts)

        BarRepo.save_bars_daily(self._db, bars_df)

        retrieved = BarRepo.get_bars_daily(
            self._db, ["000001.SZ"], "2025-07-01", "2025-07-07"
        )

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            assert col in retrieved.columns, f"Column {col} missing from retrieved data"

        for i in range(len(retrieved)):
            assert retrieved["ticker"][i] == "000001.SZ"

        first_date = retrieved["trade_date"].sort()[0]
        assert str(first_date) >= "2025-07-01"

        high_values = retrieved["high"].to_list()
        low_values = retrieved["low"].to_list()
        assert all(h >= l for h, l in zip(high_values, low_values) if h is not None and l is not None)
