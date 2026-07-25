import polars as pl
from pathlib import Path
import re

FACTOR_DIR = "data/factors"


def sanitize_column(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


class FactorStorage:
    @staticmethod
    def save(symbol: str, factor_df: pl.DataFrame):
        symbol_safe = sanitize_column(symbol)
        dir_path = Path(FACTOR_DIR) / symbol_safe
        dir_path.mkdir(parents=True, exist_ok=True)
        renamed = factor_df.rename({c: sanitize_column(c) for c in factor_df.columns})
        path = dir_path / "factors.parquet"
        if path.exists():
            existing = pl.read_parquet(path)
            for col in renamed.columns:
                if col in existing.columns:
                    existing = existing.drop(col)
            merged = existing.hstack(renamed)
            merged.write_parquet(path)
        else:
            renamed.write_parquet(path)

    @staticmethod
    def load(symbol: str) -> pl.DataFrame | None:
        symbol_safe = sanitize_column(symbol)
        path = Path(FACTOR_DIR) / symbol_safe / "factors.parquet"
        if not path.exists():
            return None
        return pl.read_parquet(path)

    @staticmethod
    def delete(symbol: str):
        import shutil
        symbol_safe = sanitize_column(symbol)
        dir_path = Path(FACTOR_DIR) / symbol_safe
        if dir_path.exists():
            shutil.rmtree(dir_path)

    @staticmethod
    def load_with_factors(symbol: str, ohlcv_df: pl.DataFrame) -> pl.DataFrame:
        factors = FactorStorage.load(symbol)
        if factors is None:
            return ohlcv_df
        n = min(len(ohlcv_df), len(factors))
        return ohlcv_df[:n].hstack(factors[:n])
