from .base import Strategy
from .registry import StrategyRegistry


class StrategyEngine:
    def __init__(self):
        self._strategies: dict[str, Strategy] = {}
        self._paused: set[str] = set()

    def load(self, name: str, params: dict | None = None) -> Strategy:
        cls = StrategyRegistry.get(name)
        instance = cls(params)
        self._strategies[name] = instance
        return instance

    async def on_bar(self, bar):
        for name, s in self._strategies.items():
            if name not in self._paused:
                await s.on_bar(bar)

    def collect_signals(self) -> list:
        signals = []
        for name, s in self._strategies.items():
            if name not in self._paused:
                signals.extend(s.on_signal())
        return signals

    def pause(self, name: str):
        if name in self._strategies:
            self._paused.add(name)

    def resume(self, name: str):
        self._paused.discard(name)

    def is_paused(self, name: str) -> bool:
        return name in self._paused

    def get_strategy(self, name: str) -> Strategy | None:
        return self._strategies.get(name)

    def list_loaded(self) -> list[str]:
        return list(self._strategies.keys())
