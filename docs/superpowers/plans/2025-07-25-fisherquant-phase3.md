# FisherQuant Phase 3 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Build Strategy Engine (ABC lifecycle, registry, YAML pipeline, 6 strategy types) and Portfolio Builder (signal merging, weight calculation, order generation).

**Architecture:** Strategy follows ABC pattern with lifecycle hooks (on_init, on_bar, on_signal, on_order_filled). PortfolioBuilder sits between Strategy and Risk — consuming Signal[] and producing Order[]. YAML pipelines compose factor → model → portfolio stages.

**Tech Stack:** Python 3.11+, polars, pydantic, pyyaml

## Global Constraints

- Python >= 3.11
- Strategy ABC: on_init, on_bar, on_signal, on_order_filled, on_risk_close, serialize_state, restore_state
- PortfolioBuilder: signals → weights → target holdings → orders
- Conflict modes: skip_conflict, weighted_merge, first_wins
- Portfolio methods: equal_weight, risk_parity, kelly
- YAML pipeline: data → factor → model → portfolio → risk stages
- All public functions type annotated

---

### Task 1: Strategy Base Class

**Files:** fisher/strategy/__init__.py, base.py, tests/unit/test_strategy_base.py

```python
# fisher/strategy/base.py
from abc import ABC, abstractmethod
from ...event.types import Bar, Signal, OrderFilled, OrderSide


class Strategy(ABC):
    name: str = "base_strategy"

    def __init__(self, params: dict | None = None):
        self.params = params or {}
        self._signals: list[Signal] = []

    async def on_init(self): pass

    @abstractmethod
    async def on_bar(self, bar: Bar): ...

    def on_signal(self) -> list[Signal]:
        signals = self._signals[:]
        self._signals.clear()
        return signals

    async def on_order_filled(self, order: OrderFilled): pass

    async def on_risk_close(self, order: OrderFilled): pass

    def serialize_state(self) -> dict:
        return {"params": self.params}

    def restore_state(self, state: dict):
        self.params = state.get("params", {})

    def emit_signal(self, ticker: str, market: str, side: OrderSide,
                    quantity: int, price: float = 0.0, confidence: float = 1.0,
                    reason: str = ""):
        self._signals.append(Signal(
            strategy=self.name, ticker=ticker, market=market,
            side=side, quantity=quantity, limit_price=price,
            confidence=confidence, reason=reason,
        ))
```

Tests: verify lifecycle (on_init, on_bar, on_signal, state save/restore, signal emission).

Commit: "feat: Strategy base class with lifecycle and signal emission"

---

### Task 2: Strategy Registry + Engine

**Files:** fisher/strategy/registry.py, engine.py, tests/unit/test_strategy_registry.py

```python
# fisher/strategy/registry.py
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
```

```python
# fisher/strategy/engine.py
from .base import Strategy
from .registry import StrategyRegistry

class StrategyEngine:
    def __init__(self):
        self._strategies: dict[str, Strategy] = {}

    def load(self, name: str, params: dict | None = None) -> Strategy:
        cls = StrategyRegistry.get(name)
        instance = cls(params)
        self._strategies[name] = instance
        return instance

    async def on_bar(self, bar):
        for s in self._strategies.values():
            await s.on_bar(bar)

    def collect_signals(self) -> list:
        signals = []
        for s in self._strategies.values():
            signals.extend(s.on_signal())
        return signals

    def pause(self, name: str):
        pass  # mark for pause

    def resume(self, name: str):
        pass
```

Commit: "feat: Strategy registry and engine with load/collect/pause"

---

### Task 3: Built-in Strategies (CTA + Factor + Event)

**Files:** fisher/strategy/ (add builtin subpackage), strategies/builtin/

Implement 6 built-in strategies as subclasses:
1. MomentumStrategy (CTA) — bar.close crosses SMA(fast) above SMA(slow) → buy
2. MeanReversionStrategy (CTA) — bar.close below Bollinger lower band → buy
3. AlphaModelStrategy (Factor) — scores tickers by factor values, picks top N
4. RotationalStrategy (Factor) — rotates into best-performing tickers
5. PairTradeStrategy — two correlated tickers diverge → long cheap, short expensive
6. CompositeStrategy — wraps multiple strategies, merges their signals

Commit: "feat: 6 built-in strategy types (CTA, Factor, Pair, Composite)"

---

### Task 4: YAML Pipeline Parser

**Files:** fisher/strategy/pipeline.py, tests/unit/test_pipeline.py

Parses YAML pipeline definition into a Strategy instance by composing:
```
data → factor → model → portfolio → risk
```

```yaml
pipeline:
  universe: csi300
  lookback: 252d
  factors: [momentum_20d, volatility_60d]
  model:
    type: linear
    weights: [0.6, 0.4]
  portfolio:
    top_k: 30
    method: equal_weight
```

Commit: "feat: YAML pipeline parser for strategy composition"

---

### Task 5: Portfolio Builder

**Files:** fisher/portfolio/__init__.py, builder.py, methods.py, tests/unit/test_portfolio_builder.py

```python
# fisher/portfolio/builder.py
from ...event.types import Signal, OrderPending
from .methods import equal_weight, risk_parity, kelly

class PortfolioBuilder:
    def __init__(self, method: str = "equal_weight", max_positions: int = 20,
                 conflict_mode: str = "weighted_merge"):
        self.method = method
        self.max_positions = max_positions
        self.conflict_mode = conflict_mode
        self._current_holdings: dict[str, float] = {}

    def build_orders(self, signals: list[Signal],
                     capital: float) -> list[OrderPending]:
        merged = self._merge_signals(signals)
        weights = self._compute_weights(merged, capital)
        orders = self._weights_to_orders(weights, capital)
        return orders

    def _merge_signals(self, signals: list[Signal]) -> dict[str, dict]:
        ticker_signals: dict[str, list[Signal]] = {}
        for s in signals:
            ticker_signals.setdefault(s.ticker, []).append(s)

        merged = {}
        for ticker, sigs in ticker_signals.items():
            if len(sigs) > 1 and self.conflict_mode == "skip_conflict":
                continue
            if self.conflict_mode == "weighted_merge":
                total_qty = sum(s.quantity for s in sigs)
                avg_confidence = sum(s.confidence for s in sigs) / len(sigs)
                dominant = max(sigs, key=lambda s: s.confidence)
                merged[ticker] = {
                    "ticker": ticker, "market": dominant.market,
                    "side": dominant.side, "quantity": total_qty,
                    "confidence": avg_confidence,
                }
            elif self.conflict_mode == "first_wins":
                s = sigs[0]
                merged[ticker] = {"ticker": ticker, "market": s.market,
                    "side": s.side, "quantity": s.quantity,
                    "confidence": s.confidence}
        return merged

    def _compute_weights(self, merged, capital):
        if self.method == "equal_weight":
            return equal_weight(merged, self.max_positions)
        elif self.method == "risk_parity":
            return risk_parity(merged, capital)
        elif self.method == "kelly":
            return kelly(merged)
        return equal_weight(merged, self.max_positions)
```

```python
# fisher/portfolio/methods.py
def equal_weight(merged: dict, max_positions: int) -> dict:
    selected = dict(list(merged.items())[:max_positions])
    weight = 1.0 / max(len(selected), 1)
    return {t: weight for t in selected}

def risk_parity(merged: dict, capital: float) -> dict:
    n = len(merged)
    if n == 0:
        return {}
    weight = 1.0 / n
    return {t: weight for t in merged}

def kelly(merged: dict) -> dict:
    n = len(merged)
    if n == 0:
        return {}
    weight = 1.0 / n
    return {t: weight for t in merged}
```

Tests: 3 signal merge → weights → orders, conflict modes, max_positions limiting.

Commit: "feat: Portfolio builder with signal merging and weight methods"

---

### Task 6: Integration — Strategy → Portfolio Pipeline

**Files:** tests/integration/test_strategy_to_portfolio.py

Test end-to-end: load MomentumStrategy → feed bars → collect signals → PortfolioBuilder → verify orders.

Commit: "feat: strategy-to-portfolio integration test"
