from abc import ABC, abstractmethod
import polars as pl


class Factor(ABC):
    name: str = ""
    category: str = ""

    @property
    def output_columns(self) -> list[str]:
        return [self.name]

    @abstractmethod
    def compute(self, df: pl.DataFrame) -> pl.DataFrame: ...
