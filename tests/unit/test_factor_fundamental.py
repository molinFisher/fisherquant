import polars as pl
import pytest
from fisher.factor.fundamental import PB, PE, ROE


class TestPB:
    def test_pb_computes_ratio(self):
        f = PB()
        df = pl.DataFrame({
            "close": [20.0, 30.0, 15.0],
            "book_value_per_share": [10.0, 10.0, 5.0],
        })
        result = f.compute(df)
        assert "pb_ratio" in result.columns
        assert result["pb_ratio"].to_list() == [2.0, 3.0, 3.0]

    def test_pb_missing_columns_raises(self):
        f = PB()
        df = pl.DataFrame({"close": [10.0]})
        with pytest.raises(ValueError, match="book_value_per_share"):
            f.compute(df)


class TestPE:
    def test_pe_computes_ratio(self):
        f = PE()
        df = pl.DataFrame({
            "close": [100.0, 50.0],
            "earnings_per_share": [5.0, 2.0],
        })
        result = f.compute(df)
        assert result["pe_ratio"].to_list() == [20.0, 25.0]

    def test_pe_zero_eps(self):
        f = PE()
        df = pl.DataFrame({
            "close": [100.0],
            "earnings_per_share": [0.0],
        })
        result = f.compute(df)
        assert result["pe_ratio"][0] == float("inf")


class TestROE:
    def test_roe_computes_percentage(self):
        f = ROE()
        df = pl.DataFrame({
            "net_income": [15.0, 20.0],
            "book_value": [100.0, 200.0],
        })
        result = f.compute(df)
        assert result["roe"].to_list() == [15.0, 10.0]

    def test_roe_missing_columns_raises(self):
        f = ROE()
        df = pl.DataFrame({"net_income": [15.0]})
        with pytest.raises(ValueError, match="book_value"):
            f.compute(df)
