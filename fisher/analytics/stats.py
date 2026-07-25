import math


def compute_beta(returns_p: list[float], returns_b: list[float]) -> float:
    n = min(len(returns_p), len(returns_b))
    if n < 2:
        return 0.0
    p = returns_p[-n:]
    b = returns_b[-n:]
    mean_p = sum(p) / n
    mean_b = sum(b) / n
    cov = sum((p[i] - mean_p) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (n - 1)
    if var_b == 0:
        return 0.0
    return cov / var_b


def compute_mean(rets: list[float]) -> float:
    return sum(rets) / len(rets) if rets else 0.0


def compute_variance(rets: list[float]) -> float:
    n = len(rets)
    if n < 2:
        return 0.0
    mean = compute_mean(rets)
    return sum((r - mean) ** 2 for r in rets) / (n - 1)


def compute_std(rets: list[float]) -> float:
    return math.sqrt(compute_variance(rets))
