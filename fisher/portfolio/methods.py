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
