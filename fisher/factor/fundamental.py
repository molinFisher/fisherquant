import polars as pl
from .base import Factor


class PB(Factor):
    name = "pb_ratio"
    category = "fundamental"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns or "book_value_per_share" not in df.columns:
            raise ValueError("DataFrame must have 'close' and 'book_value_per_share' columns")
        return df.with_columns(
            (pl.col("close") / pl.col("book_value_per_share")).alias(self.name)
        )


class PE(Factor):
    name = "pe_ratio"
    category = "fundamental"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "close" not in df.columns or "earnings_per_share" not in df.columns:
            raise ValueError("DataFrame must have 'close' and 'earnings_per_share' columns")
        return df.with_columns(
            (pl.col("close") / pl.col("earnings_per_share")).alias(self.name)
        )


class ROE(Factor):
    name = "roe"
    category = "fundamental"

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        if "net_income" not in df.columns or "book_value" not in df.columns:
            raise ValueError("DataFrame must have 'net_income' and 'book_value' columns")
        return df.with_columns(
            ((pl.col("net_income") / pl.col("book_value")) * 100).alias(self.name)
        )
