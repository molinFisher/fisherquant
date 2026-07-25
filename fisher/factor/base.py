from abc import ABC, abstractmethod
import polars as pl


class Factor(ABC):
    name: str = ""
    category: str = ""

    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame: ...
