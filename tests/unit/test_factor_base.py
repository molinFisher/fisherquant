import polars as pl
from fisher.factor.base import Factor


class MockFactor(Factor):
    name = "mock_factor"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.col("close").alias(self.name))


class TestFactor:
    def test_factor_name(self):
        f = MockFactor()
        assert f.name == "mock_factor"

    def test_factor_category(self):
        f = MockFactor()
        assert f.category == "price"

    def test_compute_returns_dataframe(self):
        f = MockFactor()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert "mock_factor" in result.columns
        assert result["mock_factor"].to_list() == [10.0, 10.5, 11.0]

    def test_compute_preserves_original_columns(self):
        f = MockFactor()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert "close" in result.columns
