from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


def cross_above(series_a, series_b, threshold: float = 0.0):
    result = [False] * len(series_a)
    for i in range(1, len(series_a)):
        if series_a[i - 1] <= series_b[i - 1] + threshold and series_a[i] > series_b[i] + threshold:
            result[i] = True
    return result


def cross_below(series_a, series_b, threshold: float = 0.0):
    result = [False] * len(series_a)
    for i in range(1, len(series_a)):
        if series_a[i - 1] >= series_b[i - 1] - threshold and series_a[i] < series_b[i] - threshold:
            result[i] = True
    return result


def threshold_check(series, operator: str, value: float):
    ops = {
        "gt": lambda s, v: s > v, "lt": lambda s, v: s < v,
        "gte": lambda s, v: s >= v, "lte": lambda s, v: s <= v, "eq": lambda s, v: s == v,
    }
    op = ops.get(operator, ops["gt"])
    return [op(s, value) for s in series]


PRIMITIVES = {
    "cross_above": cross_above,
    "cross_below": cross_below,
    "threshold": threshold_check,
}


@dataclass
class DSLSignal:
    buy: list[bool] = field(default_factory=list)
    sell: list[bool] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)


class DSLEngine:
    def evaluate(self, config: dict, data: dict) -> DSLSignal:
        buy_rule = config.get("buy_rule")
        sell_rule = config.get("sell_rule")
        n = len(next(iter(data.values()), []))

        buy_signal = [False] * n
        sell_signal = [False] * n

        if buy_rule:
            buy_signal = self._evaluate_rule(buy_rule, data)

        if sell_rule:
            sell_signal = self._evaluate_rule(sell_rule, data)

        weights = [0.0] * n
        for i in range(n):
            if buy_signal[i]:
                weights[i] = 1.0
            elif sell_signal[i]:
                weights[i] = -1.0

        return DSLSignal(buy=buy_signal, sell=sell_signal, weights=weights)

    def _evaluate_rule(self, rule: dict, data: dict) -> list[bool]:
        rule_type = rule.get("type", "primitive")
        if rule_type == "primitive":
            return self._eval_primitive(rule, data)
        elif rule_type == "composite":
            return self._eval_composite(rule, data)
        raise ValueError(f"Unknown rule type: {rule_type}")

    def _eval_primitive(self, rule: dict, data: dict) -> list[bool]:
        name = rule["name"]
        args = rule.get("args", [])
        kwargs = rule.get("kwargs", {})
        prim = PRIMITIVES.get(name)
        if prim is None:
            raise ValueError(f"Unknown primitive: {name}")
        resolved_args = [data.get(a, a) if isinstance(a, str) else a for a in args]
        return prim(*resolved_args, **kwargs)

    def _eval_composite(self, rule: dict, data: dict) -> list[bool]:
        op = rule.get("operator", "AND")
        sub_rules = rule.get("rules", [])
        if not sub_rules:
            return []
        results = [self._evaluate_rule(r, data) for r in sub_rules]
        n = len(results[0])
        combined = [False] * n
        for i in range(n):
            vals = [r[i] for r in results]
            combined[i] = all(vals) if op == "AND" else any(vals)
        return combined


def validate_dsl(config: dict) -> list[str]:
    errors = []
    for key in ["buy_rule", "sell_rule"]:
        if key in config and config[key]:
            errors += _validate_rule(config[key], key)
    return errors


def _validate_rule(rule: dict, path: str) -> list[str]:
    errors = []
    if not isinstance(rule, dict):
        return [f"{path}: must be a dict"]
    rt = rule.get("type")
    if rt not in ("primitive", "composite"):
        errors.append(f"{path}: type must be 'primitive' or 'composite'")
        return errors
    if rt == "primitive":
        name = rule.get("name", "")
        if name not in PRIMITIVES:
            errors.append(f"{path}: unknown primitive '{name}', must be one of {list(PRIMITIVES.keys())}")
    elif rt == "composite":
        op = rule.get("operator", "")
        if op not in ("AND", "OR"):
            errors.append(f"{path}: composite operator must be AND or OR")
        for i, sub in enumerate(rule.get("rules", [])):
            errors += _validate_rule(sub, f"{path}.rules[{i}]")
    return errors
