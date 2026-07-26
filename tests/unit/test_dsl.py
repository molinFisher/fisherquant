"""Unit tests for fisher/strategy/dsl.py (DSL 表达式引擎与校验).

覆盖 cross_above / cross_below / threshold_check 原语，DSLEngine.evaluate 的
primitive 与 composite(AND/OR) 规则、weights 推导，以及 _evaluate_rule /
_eval_primitive 的异常路径与 validate_dsl 的配置校验。
"""
import pytest

from fisher.strategy.dsl import (
    DSLEngine,
    validate_dsl,
    cross_above,
    cross_below,
    threshold_check,
)


def test_cross_above():
    a = [1, 2, 3, 5, 4]
    b = [2, 2, 2, 2, 2]
    assert cross_above(a, b) == [False, False, True, False, False]


def test_cross_below():
    a = [5, 4, 3, 1, 2]
    b = [2, 2, 2, 2, 2]
    assert cross_below(a, b) == [False, False, False, True, False]


def test_threshold_operators():
    s = [1, 2, 3, 4, 5]
    assert threshold_check(s, "gt", 3) == [False, False, False, True, True]
    assert threshold_check(s, "lt", 3) == [True, True, False, False, False]
    assert threshold_check(s, "gte", 3) == [False, False, True, True, True]
    assert threshold_check(s, "lte", 3) == [True, True, True, False, False]
    assert threshold_check(s, "eq", 3) == [False, False, True, False, False]


def test_dsl_evaluate_buy_sell_and_weights():
    eng = DSLEngine()
    cfg = {
        "buy_rule": {
            "type": "primitive", "name": "threshold",
            "args": ["close", "gt", 15], "kwargs": {},
        },
        "sell_rule": {
            "type": "primitive", "name": "threshold",
            "args": ["close", "lt", 5], "kwargs": {},
        },
    }
    out = eng.evaluate(cfg, {"close": [1, 10, 20]})
    assert out.buy == [False, False, True]
    assert out.sell == [True, False, False]
    assert out.weights == [-1.0, 0.0, 1.0]


def test_dsl_composite_and():
    eng = DSLEngine()
    cfg = {
        "buy_rule": {
            "type": "composite", "operator": "AND",
            "rules": [
                {"type": "primitive", "name": "threshold", "args": ["close", "gt", 10], "kwargs": {}},
                {"type": "primitive", "name": "threshold", "args": ["close", "lt", 20], "kwargs": {}},
            ],
        }
    }
    out = eng.evaluate(cfg, {"close": [5, 15, 25]})
    assert out.buy == [False, True, False]


def test_dsl_composite_or():
    eng = DSLEngine()
    cfg = {
        "buy_rule": {
            "type": "composite", "operator": "OR",
            "rules": [
                {"type": "primitive", "name": "threshold", "args": ["close", "gt", 20], "kwargs": {}},
                {"type": "primitive", "name": "threshold", "args": ["close", "lt", 5], "kwargs": {}},
            ],
        }
    }
    out = eng.evaluate(cfg, {"close": [3, 15, 25]})
    assert out.buy == [True, False, True]


def test_dsl_empty_rules_no_signal():
    eng = DSLEngine()
    out = eng.evaluate({}, {"close": [1, 2, 3]})
    assert out.buy == [False, False, False]
    assert out.sell == [False, False, False]


def test_dsl_unknown_rule_type_raises():
    eng = DSLEngine()
    with pytest.raises(ValueError):
        eng._evaluate_rule({"type": "bogus"}, {"close": [1]})


def test_dsl_unknown_primitive_raises():
    eng = DSLEngine()
    with pytest.raises(ValueError):
        eng._evaluate_rule(
            {"type": "primitive", "name": "nope", "args": []}, {"close": [1]}
        )


def test_validate_dsl_ok():
    cfg = {"buy_rule": {"type": "primitive", "name": "threshold",
                        "args": ["close", "gt", 1], "kwargs": {}}}
    assert validate_dsl(cfg) == []


def test_validate_dsl_unknown_primitive():
    cfg = {"buy_rule": {"type": "primitive", "name": "bogus"}}
    errs = validate_dsl(cfg)
    assert any("unknown primitive" in e for e in errs)


def test_validate_dsl_bad_type():
    cfg = {"buy_rule": {"type": "weird"}}
    errs = validate_dsl(cfg)
    assert any("type must be" in e for e in errs)


def test_validate_dsl_bad_composite_operator():
    cfg = {"buy_rule": {"type": "composite", "operator": "XOR", "rules": []}}
    errs = validate_dsl(cfg)
    assert any("AND or OR" in e for e in errs)
