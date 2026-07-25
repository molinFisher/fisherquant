import pytest
import polars as pl
from fisher.factor.base import Factor
from fisher.factor.registry import FactorRegistry


class FakeFactor(Factor):
    name = "fake"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df


class TestFactorRegistry:
    def setup_method(self):
        FactorRegistry._factors.clear()

    def test_register_and_get(self):
        f = FakeFactor()
        FactorRegistry.register(f)
        assert FactorRegistry.get("fake") is f

    def test_list_all(self):
        FactorRegistry.register(FakeFactor())
        all_factors = FactorRegistry.list_all()
        assert len(all_factors) == 1
        assert all_factors[0].name == "fake"

    def test_get_missing_raises(self):
        with pytest.raises(KeyError):
            FactorRegistry.get("nonexistent")

    def test_list_by_category(self):
        FactorRegistry.register(FakeFactor())
        price_factors = FactorRegistry.list_by_category("price")
        assert len(price_factors) == 1
        fundamental = FactorRegistry.list_by_category("fundamental")
        assert len(fundamental) == 0

    def test_register_duplicate_overwrites(self):
        f1 = FakeFactor()
        f2 = FakeFactor()
        FactorRegistry.register(f1)
        FactorRegistry.register(f2)
        assert FactorRegistry.get("fake") is f2
