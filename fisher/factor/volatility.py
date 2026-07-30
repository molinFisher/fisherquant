import polars as pl
from .base import Factor


class Atr(Factor):
    """平均真实波幅（Average True Range）。

    - 前复权口径：若传入 adj_factor（来自 adj_factors.adj_type='qfq'），
      则先按「最新日因子」归一得到前复权 OHLC 再计算 TR，避免除权缺口造成
      TR 虚假放大；若缺失（全 null）则降级为不复权计算。
    - v1 采用简单滚动均值；Wilder 平滑列为后续开关。
    """

    name = "atr"
    category = "volatility"
    default_period = 14

    @property
    def output_columns(self) -> list[str]:
        return ["atr", "tr"]

    def compute(self, df: pl.DataFrame) -> pl.DataFrame:
        for col in ("open", "high", "low", "close"):
            if col not in df.columns:
                raise ValueError(f"DataFrame must have '{col}' column")

        high = pl.col("high")
        low = pl.col("low")
        close = pl.col("close")
        prev_close = close.shift(1)

        # 前复权：系统存储 adj_factor = raw_close / qfq_close，
        # 故 前复权价 = raw / adj_factor（即 qfq 价，已去除除权缺口，序列连续）。
        # 注意：prev_close 须用「前复权后的前收」，即 (close/adj_factor).shift(1)，
        # 不能直接 close.shift(1)/adj_factor（会错用当前行复权因子导致对齐错位）。
        use_adj = "adj_factor" in df.columns and df["adj_factor"].null_count() == 0
        if use_adj:
            af = pl.col("adj_factor")
            adj_close_prev = (close / af).shift(1)
            h = high / af
            l = low / af
            pc = adj_close_prev
        else:
            h, l, pc = high, low, prev_close

        tr = pl.max_horizontal(
            (h - l).abs(),
            (h - pc).abs(),
            (l - pc).abs(),
        )
        period = self.default_period
        atr = tr.rolling_mean(period, min_samples=period)
        return df.with_columns(tr.alias("tr"), atr.alias("atr"))
