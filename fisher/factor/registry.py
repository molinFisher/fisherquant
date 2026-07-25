from .base import Factor


class FactorRegistry:
    _factors: dict[str, Factor] = {}

    @classmethod
    def register(cls, factor: Factor):
        cls._factors[factor.name] = factor

    @classmethod
    def get(cls, name: str) -> Factor:
        if name not in cls._factors:
            raise KeyError(f"Factor '{name}' not registered")
        return cls._factors[name]

    @classmethod
    def list_all(cls) -> list[Factor]:
        return list(cls._factors.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[Factor]:
        return [f for f in cls._factors.values() if f.category == category]
