import polars as pl
from .base import Factor


class MACD(Factor):
    name = "macd"
    category = "technical"

    @property
    def output_columns(self) -> list[str]:
        return ["macd_dif", "macd_dea", "macd_hist"]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns:
            raise ValueError("DataFrame must have 'close' column")
        ema12 = pl.col("close").ewm_mean(span=12, adjust=False)
        ema26 = pl.col("close").ewm_mean(span=26, adjust=False)
        dif = ema12 - ema26
        dea = dif.ewm_mean(span=9, adjust=False)
        macd_hist = 2 * (dif - dea)
        return df.with_columns(
            dif.alias("macd_dif"),
            dea.alias("macd_dea"),
            macd_hist.alias("macd_hist"),
        )


class RSI14(Factor):
    name = "rsi_14"
    category = "technical"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns:
            raise ValueError("DataFrame must have 'close' column")
        delta = pl.col("close").diff()
        gain = delta.clip(lower_bound=0)
        loss = (-delta).clip(lower_bound=0)
        avg_gain = gain.ewm_mean(span=27, adjust=False)
        avg_loss = loss.ewm_mean(span=27, adjust=False) + 1e-10
        rs = avg_gain / avg_loss
        return df.with_columns(
            (100 - (100 / (1 + rs))).alias(self.name)
        )


class BollingerBands(Factor):
    name = "bollinger"
    category = "technical"

    @property
    def output_columns(self) -> list[str]:
        return ["bollinger_mid", "bollinger_upper", "bollinger_lower"]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns:
            raise ValueError("DataFrame must have 'close' column")
        mid = pl.col("close").rolling_mean(20)
        std = pl.col("close").rolling_std(20)
        return df.with_columns(
            mid.alias("bollinger_mid"),
            (mid + 2 * std).alias("bollinger_upper"),
            (mid - 2 * std).alias("bollinger_lower"),
        )
