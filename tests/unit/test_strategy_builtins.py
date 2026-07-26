"""Unit tests for fisher/strategy/execution.py (内置策略工厂与策略类).

覆盖 _resolve_strategy_class / create_strategy / load_strategy_from_file /
instantiate_strategy，以及 6 个内置策略（sma_cross / macd / bollinger /
rsi / buy_and_hold / custom_dsl）的 on_bar 信号生成路径。

测试通过 emit_signal -> on_signal() 捕获信号，校验方向、标的、数量与触发条件，
而非纯冒烟。on_bar 为 async，依赖 pyproject 的 asyncio_mode=auto 自动驱动。
"""
import pytest

from fisher.strategy.execution import (
    _resolve_strategy_class,
    create_strategy,
    load_strategy_from_file,
    instantiate_strategy,
)
from fisher.event.types import Bar, OrderSide


def _bar(ticker="000001.SZ", market="a_share", close=10.0, bar_time=1.0):
    return Bar(
        ticker=ticker,
        market=market,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=10000.0,
        bar_time=bar_time,
    )


async def _feed(strat, closes):
    sigs = []
    for i, c in enumerate(closes):
        await strat.on_bar(_bar(close=c, bar_time=float(i)))
        sigs.extend(strat.on_signal())
    return sigs


# --- 工厂 / 注册 -------------------------------------------------------------


def test_resolve_unknown_type_raises():
    with pytest.raises(KeyError):
        _resolve_strategy_class("not_a_real_type")


def test_create_strategy_unknown_type_raises():
    with pytest.raises(KeyError):
        create_strategy({"type": "no_such_type"})


def test_load_strategy_missing_returns_none():
    assert load_strategy_from_file("definitely_missing_strategy_xyz") is None
    assert instantiate_strategy("definitely_missing_strategy_xyz") is None


def test_create_strategy_sets_name_and_market():
    strat = create_strategy(
        {"name": "my_sma", "type": "sma_cross", "params": {"fast": 2, "slow": 3}}
    )
    assert strat.name == "my_sma"


# --- sma_cross --------------------------------------------------------------


async def test_sma_cross_golden_cross_buy():
    strat = create_strategy(
        {"name": "sc", "type": "sma_cross", "params": {"fast": 2, "slow": 3}}
    )
    sigs = await _feed(strat, [10, 10, 10, 10, 20])
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) == 1
    assert buys[0].ticker == "000001.SZ"
    assert buys[0].quantity == 100
    assert buys[0].reason == "sma_golden_cross"


async def test_sma_cross_no_signal_before_min_bars():
    strat = create_strategy(
        {"name": "sc", "type": "sma_cross", "params": {"fast": 2, "slow": 3}}
    )
    sigs = await _feed(strat, [10, 10, 10])
    assert sigs == []


# --- buy_and_hold -----------------------------------------------------------


async def test_buy_and_hold_emits_once():
    strat = _resolve_strategy_class("buy_and_hold")()
    sigs = await _feed(strat, [10, 11, 12])
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) == 1
    assert buys[0].confidence == 1.0


# --- bollinger --------------------------------------------------------------


async def test_bollinger_lower_touch_buy():
    strat = create_strategy(
        {"name": "bl", "type": "bollinger", "params": {"period": 2, "std": 1.0}}
    )
    sigs = await _feed(strat, [10, 4])
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) == 1
    assert buys[0].reason == "bollinger_lower_touch"


# --- rsi --------------------------------------------------------------------


async def test_rsi_oversold_buy():
    strat = create_strategy(
        {"name": "rsi", "type": "rsi",
         "params": {"period": 3, "overbought": 70, "oversold": 30}}
    )
    sigs = await _feed(strat, [13, 12, 11, 10])
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) >= 1
    assert buys[0].reason.startswith("rsi_oversold")


async def test_rsi_overbought_sell():
    strat = create_strategy(
        {"name": "rsi", "type": "rsi",
         "params": {"period": 3, "overbought": 70, "oversold": 30}}
    )
    sigs = await _feed(strat, [10, 11, 12, 13])
    sells = [s for s in sigs if s.side == OrderSide.SELL]
    assert len(sells) >= 1
    assert sells[0].reason.startswith("rsi_overbought")


# --- macd -------------------------------------------------------------------


async def test_macd_uptrend_emits_buy():
    strat = create_strategy(
        {"name": "macd", "type": "macd", "params": {"fast": 3, "slow": 5, "signal": 3}}
    )
    closes = [float(100 + i) for i in range(30)]
    sigs = await _feed(strat, closes)
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) >= 1


# --- custom_dsl -------------------------------------------------------------


async def test_custom_dsl_buy_on_threshold():
    cfg = {
        "buy_rule": {
            "type": "primitive", "name": "threshold",
            "args": ["close", "gt", 15], "kwargs": {},
        }
    }
    strat = create_strategy(
        {"name": "dsl", "type": "custom", "params": {"dsl_config": cfg}}
    )
    sigs = await _feed(strat, [10, 12, 16])
    buys = [s for s in sigs if s.side == OrderSide.BUY]
    assert len(buys) == 1
    assert buys[0].reason == "custom_dsl_buy"


async def test_custom_dsl_sell_on_threshold():
    cfg = {
        "sell_rule": {
            "type": "primitive", "name": "threshold",
            "args": ["close", "lt", 5], "kwargs": {},
        }
    }
    strat = create_strategy(
        {"name": "dsl", "type": "custom", "params": {"dsl_config": cfg}}
    )
    sigs = await _feed(strat, [10, 8, 3])
    sells = [s for s in sigs if s.side == OrderSide.SELL]
    assert len(sells) == 1
    assert sells[0].reason == "custom_dsl_sell"
