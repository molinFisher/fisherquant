import json
from pathlib import Path
from typing import Any

from .base import Strategy
from .registry import StrategyRegistry

STRATEGIES_DIR = Path("strategies")

STRATEGY_TYPE_REGISTRY: dict[str, type[Strategy]] = {}


def register_strategy_types():
    """Register builtin strategy types into STRATEGY_TYPE_REGISTRY."""
    from .builtin.mean_reversion import MeanReversionStrategy
    from .builtin.momentum import MomentumStrategy
    from .builtin.pair_trade import PairTradeStrategy
    from .builtin.rotational import RotationalStrategy
    from .builtin.composite import CompositeStrategy
    from .builtin.alpha_model import AlphaModelStrategy

    STRATEGY_TYPE_REGISTRY.update({
        "mean_reversion": MeanReversionStrategy,
        "momentum": MomentumStrategy,
        "pair_trade": PairTradeStrategy,
        "rotational": RotationalStrategy,
        "composite": CompositeStrategy,
        "alpha_model": AlphaModelStrategy,
    })

    StrategyRegistry._strategies.update(STRATEGY_TYPE_REGISTRY)


def create_strategy(config: dict) -> Strategy:
    """
    Create a Strategy instance from a config dictionary.

    Config format (from strategies/{name}.json):
        {
            "name": "...",
            "type": "sma_cross" | "macd" | "bollinger" | "rsi" | "buy_and_hold" | "custom",
            "description": "...",
            "params": {...},
            "symbols": [...],
            "enabled": true,
        }
    """
    stype = config.get("type", "")
    params = config.get("params", {})

    strat_cls = _resolve_strategy_class(stype)
    instance = strat_cls(params)
    instance.name = config.get("name", instance.name)
    return instance


def load_strategy_from_file(name: str) -> dict | None:
    """Load a strategy JSON config by name."""
    filepath = STRATEGIES_DIR / f"{name}.json"
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def instantiate_strategy(name: str) -> Strategy | None:
    """Load config from file and create strategy instance."""
    config = load_strategy_from_file(name)
    if config is None:
        return None
    return create_strategy(config)


def _resolve_strategy_class(stype: str) -> type[Strategy]:
    type_map = {
        "sma_cross": _make_sma_cross_strategy,
        "macd": _make_macd_strategy,
        "bollinger": _make_bollinger_strategy,
        "rsi": _make_rsi_strategy,
        "buy_and_hold": _make_buy_hold_strategy,
        "custom": _make_custom_dsl_strategy,
    }

    factory = type_map.get(stype)
    if factory is None:
        raise KeyError(
            f"Unknown strategy type '{stype}'. Known types: {list(type_map.keys())}"
        )
    return factory()


def _make_sma_cross_strategy() -> type[Strategy]:
    from collections import deque
    from ..event.types import Bar, OrderSide

    class SMACrossStrategy(Strategy):
        name = "sma_cross"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._fast = max(self.params.get("fast", 5), 1)
            self._slow = max(self.params.get("slow", 20), 2)
            self._prices: dict[str, deque] = {}

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            if ticker not in self._prices:
                self._prices[ticker] = deque(maxlen=self._slow + 1)
            self._prices[ticker].append(bar.close)
            prices = self._prices[ticker]
            if len(prices) < self._slow + 1:
                return
            plist = list(prices)
            fast_now = sum(plist[-self._fast:]) / self._fast
            slow_now = sum(plist[-self._slow:]) / self._slow
            fast_prev = sum(plist[-(self._fast+1):-1]) / self._fast
            slow_prev = sum(plist[-(self._slow+1):-1]) / self._slow
            if fast_prev <= slow_prev and fast_now > slow_now:
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.8, "sma_golden_cross")
            elif fast_prev >= slow_prev and fast_now < slow_now:
                self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.8, "sma_death_cross")

    return SMACrossStrategy


def _make_macd_strategy() -> type[Strategy]:
    from collections import deque
    from ..event.types import Bar, OrderSide

    class MACDStrategy(Strategy):
        name = "macd"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._fast_period = max(self.params.get("fast", 12), 1)
            self._slow_period = max(self.params.get("slow", 26), 2)
            self._signal_period = max(self.params.get("signal", 9), 1)
            self._prices: dict[str, deque] = {}
            self._dif_history: dict[str, deque] = {}
            self._dea_history: dict[str, deque] = {}

        def _ema(self, data: list[float], period: int) -> float:
            if len(data) < period:
                return sum(data) / len(data)
            k = 2.0 / (period + 1)
            ema = sum(data[:period]) / period
            for val in data[period:]:
                ema = val * k + ema * (1 - k)
            return ema

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            max_period = self._slow_period + self._signal_period
            if ticker not in self._prices:
                self._prices[ticker] = deque(maxlen=max_period + 1)
                self._dif_history[ticker] = deque(maxlen=self._signal_period + 1)
                self._dea_history[ticker] = deque(maxlen=self._signal_period + 1)
            self._prices[ticker].append(bar.close)
            prices = list(self._prices[ticker])
            if len(prices) < self._fast_period + 1:
                return
            fast_ema = self._ema(prices, self._fast_period)
            slow_ema = self._ema(prices, self._slow_period)
            dif = fast_ema - slow_ema
            self._dif_history[ticker].append(dif)
            dif_list = list(self._dif_history[ticker])
            if len(dif_list) < self._signal_period + 1:
                return
            dea = self._ema(dif_list, self._signal_period)
            self._dea_history[ticker].append(dea)
            dea_list = list(self._dea_history[ticker])
            if len(dea_list) < 2:
                return
            prev_dif, curr_dif = dif_list[-2], dif_list[-1]
            prev_dea, curr_dea = dea_list[-2], dea_list[-1]
            if prev_dif <= prev_dea and curr_dif > curr_dea:
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.8, "macd_golden_cross")
            elif prev_dif >= prev_dea and curr_dif < curr_dea:
                self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.8, "macd_death_cross")

    return MACDStrategy


def _make_bollinger_strategy() -> type[Strategy]:
    from collections import deque
    from ..event.types import Bar, OrderSide
    import math

    class BollingerStrategy(Strategy):
        name = "bollinger"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._period = max(self.params.get("period", 20), 1)
            self._std_mult = max(self.params.get("std", 2.0), 0.1)
            self._prices: dict[str, deque] = {}

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            if ticker not in self._prices:
                self._prices[ticker] = deque(maxlen=self._period)
            self._prices[ticker].append(bar.close)
            prices = list(self._prices[ticker])
            if len(prices) < self._period:
                return
            mean = sum(prices) / len(prices)
            variance = sum((p - mean) ** 2 for p in prices) / len(prices)
            std = math.sqrt(variance)
            upper = mean + self._std_mult * std
            lower = mean - self._std_mult * std
            if bar.close <= lower:
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.7, "bollinger_lower_touch")
            elif bar.close >= upper:
                self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.7, "bollinger_upper_touch")

    return BollingerStrategy


def _make_rsi_strategy() -> type[Strategy]:
    from collections import deque
    from ..event.types import Bar, OrderSide

    class RSIStrategy(Strategy):
        name = "rsi"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._period = max(self.params.get("period", 14), 2)
            self._overbought = min(max(self.params.get("overbought", 70), 50), 100)
            self._oversold = max(min(self.params.get("oversold", 30), 50), 0)
            self._prices: dict[str, deque] = {}
            self._gains: dict[str, deque] = {}
            self._losses: dict[str, deque] = {}

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            if ticker not in self._prices:
                self._prices[ticker] = deque(maxlen=self._period + 1)
                self._gains[ticker] = deque(maxlen=self._period)
                self._losses[ticker] = deque(maxlen=self._period)
            prev_price = self._prices[ticker][-1] if self._prices[ticker] else bar.close
            self._prices[ticker].append(bar.close)
            delta = bar.close - prev_price
            if delta > 0:
                self._gains[ticker].append(delta)
                self._losses[ticker].append(0.0)
            else:
                self._gains[ticker].append(0.0)
                self._losses[ticker].append(-delta)
            gains = list(self._gains[ticker])
            losses = list(self._losses[ticker])
            if len(gains) < self._period:
                return
            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses) + 1e-10
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            if rsi <= self._oversold:
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.7, f"rsi_oversold_{rsi:.1f}")
            elif rsi >= self._overbought:
                self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.7, f"rsi_overbought_{rsi:.1f}")

    return RSIStrategy


def _make_buy_hold_strategy() -> type[Strategy]:
    from ..event.types import Bar, OrderSide

    class BuyAndHoldStrategy(Strategy):
        name = "buy_and_hold"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            self._entered: set[str] = set()

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            if ticker not in self._entered:
                self._entered.add(ticker)
                self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 1.0, "buy_and_hold_entry")

    return BuyAndHoldStrategy


def _make_custom_dsl_strategy() -> type[Strategy]:
    from collections import deque
    from ..event.types import Bar, OrderSide
    from .dsl import DSLEngine

    class CustomDSLStrategy(Strategy):
        name = "custom_dsl"

        def __init__(self, params: dict | None = None):
            super().__init__(params)
            dsl_config = self.params.get("dsl_config", {})
            if isinstance(dsl_config, str):
                import json as _json
                dsl_config = _json.loads(dsl_config) if dsl_config else {}
            self._dsl_config = dsl_config
            self._engine = DSLEngine()
            self._price_data: dict[str, deque] = {}

        async def on_bar(self, bar: Bar):
            ticker = bar.ticker
            if ticker not in self._price_data:
                self._price_data[ticker] = deque(maxlen=200)
            self._price_data[ticker].append(bar.close)
            prices = list(self._price_data[ticker])
            if len(prices) < 2:
                return
            data = {"close": prices}
            try:
                result = self._engine.evaluate(self._dsl_config, data)
                if result.buy and len(result.buy) > 0 and result.buy[-1]:
                    self.emit_signal(ticker, bar.market, OrderSide.BUY, 100, bar.close, 0.8, "custom_dsl_buy")
                if result.sell and len(result.sell) > 0 and result.sell[-1]:
                    self.emit_signal(ticker, bar.market, OrderSide.SELL, 100, bar.close, 0.8, "custom_dsl_sell")
            except Exception:
                pass

    return CustomDSLStrategy
