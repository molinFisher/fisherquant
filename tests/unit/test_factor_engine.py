import tempfile
import os
import polars as pl
import pytest
from fisher.factor.base import Factor
from fisher.factor.registry import FactorRegistry
from fisher.factor.engine import FactorEngine
from fisher.store.engine import DuckDBEngine


class TestPriceFactor(Factor):
    name = "test_momentum"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            (pl.col("close") / pl.col("close").shift(1) - 1).alias(self.name)
        )


class TestVolFactor(Factor):
    name = "test_vol"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.col("close").rolling_std(5).alias(self.name)
        )


class TestFactorEngine:
    def setup_method(self):
        FactorRegistry._factors.clear()

    def _make_df(self):
        return pl.DataFrame({"close": [10.0, 10.5, 11.0, 10.8, 11.2]})

    def test_engine_computes_single_factor(self):
        FactorRegistry.register(TestPriceFactor())
        engine = FactorEngine()
        df = self._make_df()
        result = engine.compute(["test_momentum"], df, ticker="TEST", date="2025-01-01")
        assert "test_momentum" in result.columns
        assert "close" in result.columns

    def test_engine_computes_multiple_factors(self):
        FactorRegistry.register(TestPriceFactor())
        FactorRegistry.register(TestVolFactor())
        engine = FactorEngine()
        df = self._make_df()
        result = engine.compute(["test_momentum", "test_vol"], df, ticker="TEST", date="2025-01-01")
        assert "test_momentum" in result.columns
        assert "test_vol" in result.columns

    def test_engine_raises_for_unknown_factor(self):
        engine = FactorEngine()
        df = self._make_df()
        with pytest.raises(KeyError, match="nonexistent"):
            engine.compute(["nonexistent"], df)

    def test_engine_preserves_original_data(self):
        FactorRegistry.register(TestPriceFactor())
        engine = FactorEngine()
        df = self._make_df()
        result = engine.compute(["test_momentum"], df, ticker="TEST", date="2025-01-01")
        assert result["close"].to_list() == df["close"].to_list()

    def test_empty_factor_list_returns_original(self):
        engine = FactorEngine()
        df = self._make_df()
        result = engine.compute([], df)
        assert result.columns == df.columns


class TestFactorEngineWithCache:
    def setup_method(self):
        FactorRegistry._factors.clear()
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_factor_cache.db")
        self._db = DuckDBEngine(self._db_path)

    def teardown_method(self):
        self._db.close()
        try:
            os.unlink(self._db_path)
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    def _make_df(self):
        return pl.DataFrame({"close": [10.0, 10.5, 11.0, 10.8, 11.2]})

    def test_cache_table_initialized(self):
        FactorRegistry.register(TestPriceFactor())
        engine = FactorEngine(db_engine=self._db)
        tables = self._db.query_df(
            "SELECT table_name FROM information_schema.tables WHERE table_name='factor_cache'"
        )
        assert len(tables) > 0

    def test_cache_store_and_retrieve(self):
        FactorRegistry.register(TestPriceFactor())
        engine = FactorEngine(db_engine=self._db)
        df = self._make_df()
        engine.compute(["test_momentum"], df, ticker="000001.SZ", date="2025-01-01")

        cached = self._db.query_df(
            "SELECT * FROM factor_cache WHERE ticker='000001.SZ' AND factor_name='test_momentum'"
        )
        assert len(cached) > 0

    def test_second_call_uses_cache(self):
        FactorRegistry.register(TestPriceFactor())
        engine = FactorEngine(db_engine=self._db)
        df = self._make_df()

        result1 = engine.compute(["test_momentum"], df, ticker="000001.SZ", date="2025-01-01")
        result2 = engine.compute(["test_momentum"], df, ticker="000001.SZ", date="2025-01-01")

        assert result1["test_momentum"].to_list() == result2["test_momentum"].to_list()
