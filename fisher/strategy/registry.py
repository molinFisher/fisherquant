from .base import Strategy


class StrategyRegistry:
    _strategies: dict[str, type[Strategy]] = {}

    @classmethod
    def register(cls, strategy_cls: type[Strategy]):
        cls._strategies[strategy_cls.name] = strategy_cls

    @classmethod
    def get(cls, name: str) -> type[Strategy]:
        if name not in cls._strategies:
            raise KeyError(f"Strategy '{name}' not registered")
        return cls._strategies[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._strategies.keys())

    @classmethod
    def clear(cls):
        cls._strategies.clear()
