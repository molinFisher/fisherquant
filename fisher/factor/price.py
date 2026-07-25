import polars as pl
from .base import Factor


class Momentum20D(Factor):
    name = "momentum_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns:
            raise ValueError("DataFrame must have 'close' column")
        return df.with_columns(
            ((pl.col("close") / pl.col("close").shift(20) - 1) * 100).alias(self.name)
        )


class Momentum60D(Factor):
    name = "momentum_60d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            ((pl.col("close") / pl.col("close").shift(60) - 1) * 100).alias(self.name)
        )


class Volatility20D(Factor):
    name = "volatility_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        returns = pl.col("close").pct_change()
        return df.with_columns(
            returns.rolling_std(20).alias(self.name)
        )


class Volatility60D(Factor):
    name = "volatility_60d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        returns = pl.col("close").pct_change()
        return df.with_columns(
            returns.rolling_std(60).alias(self.name)
        )


class Turnover5D(Factor):
    name = "turnover_5d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "volume" not in df.columns or "close" not in df.columns:
            raise ValueError("DataFrame must have 'volume' and 'close' columns")
        return df.with_columns(
            pl.col("volume").rolling_mean(5).alias(self.name)
        )


class Turnover20D(Factor):
    name = "turnover_20d"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            pl.col("volume").rolling_mean(20).alias(self.name)
        )


class VolumeRatio(Factor):
    name = "volume_ratio"
    category = "price"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        vol_ma5 = pl.col("volume").rolling_mean(5)
        return df.with_columns(
            (pl.col("volume") / vol_ma5).alias(self.name)
        )
