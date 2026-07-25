import math


def equal_weight(merged: dict, max_positions: int) -> dict:
    sorted_items = sorted(
        merged.items(),
        key=lambda item: item[1].get("confidence", 0.0) if isinstance(item[1], dict) else 0.0,
        reverse=True,
    )
    selected = dict(sorted_items[:max_positions])
    weight = 1.0 / max(len(selected), 1)
    return {t: weight for t in selected}


def risk_parity(merged: dict, capital: float) -> dict:
    n = len(merged)
    if n == 0:
        return {}
    if "vol" not in next(iter(merged.values()), {}):
        return equal_weight(merged, n)
    total_inv_vol = 0.0
    weights = {}
    for ticker, info in merged.items():
        vol = abs(info.get("vol", 0.0))
        if vol == 0:
            inv_vol = 0.0
        else:
            inv_vol = 1.0 / vol
        weights[ticker] = inv_vol
        total_inv_vol += inv_vol
    if total_inv_vol == 0:
        return equal_weight(merged, n)
    return {t: w / total_inv_vol for t, w in weights.items()}


def kelly(merged: dict) -> dict:
    n = len(merged)
    if n == 0:
        return {}
    weights = {}
    total_f = 0.0
    for ticker, info in merged.items():
        p = info.get("confidence", 0.5)
        b = info.get("win_loss_ratio", 1.0)
        p = max(0.0, min(1.0, p))
        f = p - (1.0 - p) / max(b, 0.001)
        if f <= 0:
            continue
        weights[ticker] = f
        total_f += f
    if not weights:
        return equal_weight(merged, n)
    return {t: w for t, w in weights.items()}
