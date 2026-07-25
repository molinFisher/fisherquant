import pytest
import polars as pl
from fisher_temp.data_downloader import DataDownloader
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.store.repository import BarRepo
import tempfile
from pathlib import Path


@pytest.fixture
def engine():
    with tempfile.TemporaryDirectory() as d:
        eng = DuckDBEngine(str(Path(d) / "test.db"))
        init_schema(eng)
        yield eng
        eng.close()


class TestDataDownloader:
    @pytest.mark.slow
    def test_download_a_share_single_ticker(self, engine):
        dl = DataDownloader(engine)
        ticker = "000001.SZ"
        bars = dl.download_a_share(ticker, "2024-01-01", "2024-03-31")
        assert bars is not None
        assert len(bars) > 0
        for b in bars:
            assert b.close > 0
            assert b.volume >= 0

    @pytest.mark.slow
    def test_download_hk_connect_single_ticker(self, engine):
        dl = DataDownloader(engine)
        ticker = "00700.HK"
        bars = dl.download_hk_connect(ticker, "2024-01-01", "2024-03-31")
        assert bars is not None
        assert len(bars) > 0

    def test_validates_bar_fields(self, engine):
        dl = DataDownloader(engine)
        ticker = "000001.SZ"
        bars = dl.download_a_share(ticker, "2024-01-01", "2024-02-01")
        if bars:
            b = bars[0]
            assert isinstance(b.ticker, str)
            assert isinstance(b.open, float)
            assert isinstance(b.close, float)
            assert b.high >= b.low
