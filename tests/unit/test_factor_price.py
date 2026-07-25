import polars as pl
import pytest
from fisher.factor.price import (
    Momentum20D, Momentum60D, Volatility20D, Volatility60D,
    Turnover5D, Turnover20D, VolumeRatio,
)


class TestMomentum20D:
    def test_momentum_computes_pct_change(self):
        f = Momentum20D()
        close_prices = [10.0] * 21
        close_prices[-1] = 11.0
        df = pl.DataFrame({"close": close_prices})
        result = f.compute(df)
        assert "momentum_20d" in result.columns
        assert result["momentum_20d"][-1] == pytest.approx(10.0, abs=0.01)

    def test_not_enough_data_returns_null(self):
        f = Momentum20D()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert result["momentum_20d"].to_list() == [None, None, None]


class TestMomentum60D:
    def test_momentum60d_name(self):
        f = Momentum60D()
        assert f.name == "momentum_60d"

    def test_not_enough_data_returns_null(self):
        f = Momentum60D()
        df = pl.DataFrame({"close": [10.0, 10.5, 11.0]})
        result = f.compute(df)
        assert result["momentum_60d"].to_list() == [None, None, None]


class TestVolatility20D:
    def test_volatility_is_positive(self):
        f = Volatility20D()
        import random
        prices = [100.0]
        for _ in range(100):
            prices.append(prices[-1] * (1 + random.uniform(-0.02, 0.02)))
        df = pl.DataFrame({"close": prices})
        result = f.compute(df)
        assert result["volatility_20d"].drop_nulls().min() > 0


class TestVolatility60D:
    def test_volatility60d_name(self):
        f = Volatility60D()
        assert f.name == "volatility_60d"


class TestTurnover5D:
    def test_turnover_computes_rolling_mean(self):
        f = Turnover5D()
        df = pl.DataFrame({"close": [10.0] * 6, "volume": [100, 200, 300, 400, 500, 600]})
        result = f.compute(df)
        assert result["turnover_5d"][-1] == pytest.approx(400.0)


class TestTurnover20D:
    def test_turnover20d_rolling_mean(self):
        f = Turnover20D()
        volumes = list(range(1, 41))
        df = pl.DataFrame({"volume": volumes})
        result = f.compute(df)
        last_20_mean = sum(volumes[-20:]) / 20
        assert result["turnover_20d"][-1] == pytest.approx(last_20_mean)


class TestVolumeRatio:
    def test_volume_ratio(self):
        f = VolumeRatio()
        df = pl.DataFrame({"volume": [100, 100, 100, 100, 100, 200]})
        result = f.compute(df)
        assert result["volume_ratio"][-1] == pytest.approx(1.667, abs=0.01)
