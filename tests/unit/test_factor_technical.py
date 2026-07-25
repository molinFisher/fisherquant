import polars as pl
import pytest
from fisher.factor.technical import MACD, RSI14, BollingerBands


class TestMACD:
    def test_macd_produces_dea_dif_hist(self):
        f = MACD()
        prices = list(range(1, 101))
        df = pl.DataFrame({"close": prices})
        result = f.compute(df)
        assert "macd_dif" in result.columns
        assert "macd_dea" in result.columns
        assert "macd_hist" in result.columns
        assert result["macd_dif"].drop_nulls().len() > 0

    def test_macd_long_trend(self):
        f = MACD()
        df = pl.DataFrame({"close": [10.0] * 50 + [20.0] * 50})
        result = f.compute(df)
        last_dif = result["macd_dif"][-1]
        assert last_dif > 0


class TestRSI14:
    def test_rsi14_produces_series(self):
        f = RSI14()
        df = pl.DataFrame({"close": list(range(1, 31))})
        result = f.compute(df)
        assert "rsi_14" in result.columns

    def test_rsi14_all_same_price(self):
        f = RSI14()
        df = pl.DataFrame({"close": [10.0] * 30})
        result = f.compute(df)
        assert "rsi_14" in result.columns


class TestBollingerBands:
    def test_bollinger_produces_bands(self):
        f = BollingerBands()
        prices = list(range(1, 41))
        df = pl.DataFrame({"close": prices})
        result = f.compute(df)
        assert "bollinger_mid" in result.columns
        assert "bollinger_upper" in result.columns
        assert "bollinger_lower" in result.columns

    def test_bollinger_upper_above_lower(self):
        f = BollingerBands()
        import random
        prices = [100.0]
        for _ in range(50):
            prices.append(prices[-1] * (1 + random.uniform(-0.02, 0.02)))
        df = pl.DataFrame({"close": prices})
        result = f.compute(df)
        for i in range(20, len(prices) - 1):
            if result["bollinger_upper"][i] is not None:
                assert result["bollinger_upper"][i] >= result["bollinger_lower"][i]

    def test_missing_close_raises(self):
        f = BollingerBands()
        df = pl.DataFrame({"open": [10.0]})
        with pytest.raises(ValueError, match="close"):
            f.compute(df)
