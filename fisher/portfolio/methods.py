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


def risk_parity(merged: dict, capital: float = 0.0, cov: dict | None = None) -> dict:
    """风险平价（等风险贡献）。

    若提供协方差矩阵 cov（{ticker: {ticker: value}}），使用迭代法求解真正的
    等风险贡献权重；否则在"各标的收益相互独立"假设下，等风险贡献等价于
    逆波动率加权（这是逆波动率的正确含义，而非 doc 批评的"名不副实"）。
    """
    n = len(merged)
    if n == 0:
        return {}
    vols = {t: abs(info.get("vol", 0.0)) for t, info in merged.items()}
    if cov is not None:
        try:
            return _erc_with_cov(merged, vols, cov)
        except Exception:  # noqa: BLE001
            pass
    # 独立假设下的等风险贡献 = 逆波动率加权
    inv = {t: (1.0 / v if v > 0 else 0.0) for t, v in vols.items()}
    total = sum(inv.values())
    if total == 0:
        return equal_weight(merged, n)
    return {t: w / total for t, w in inv.items()}


def _erc_with_cov(merged: dict, vols: dict, cov: dict) -> dict:
    import numpy as np
    tickers = list(merged.keys())
    n = len(tickers)
    vol_arr = np.array([vols[t] for t in tickers])
    Sigma = np.eye(n)
    for i, ti in enumerate(tickers):
        for j, tj in enumerate(tickers):
            if ti == tj:
                Sigma[i, j] = vol_arr[i] ** 2
            else:
                Sigma[i, j] = cov.get(ti, {}).get(tj, 0.0)
    # 固定点迭代求等风险贡献权重
    w = np.ones(n) / n
    for _ in range(100):
        rc = w * (Sigma @ w)
        rc_safe = np.where(rc > 0, rc, 1e-12)
        w = w / rc_safe
        w = w / w.sum()
        # 收敛判定
        rc = w * (Sigma @ w)
        if rc.max() - rc.min() < 1e-9:
            break
    return {t: float(max(x, 0.0)) for t, x in zip(tickers, w)}


def kelly(merged: dict, fraction: float = 0.5, max_per_asset: float = 0.25) -> dict:
    """分数凯利（稳健版）。

    问题：原实现对每个标的独立计算 f* 后直接归一化，忽略相关性且可能放大到爆仓。
    修正：
    - 单标的 f* = p - (1-p)/b，并截断在 max_per_asset 上限（防爆仓）；
    - 乘以 fraction（默认 0.5，分数凯利更稳健）；
    - 仅在权重总和 > 1 时等比例缩减（不引入杠杆）；总和 < 1 时保留现金，
      不再向上归一化（向上归一化会重新突破单标的上限，违背防爆仓初衷）。
    注：若提供协方差矩阵与期望收益，可进一步做多元凯利（Σ^-1 μ），但当前
        信号仅含 confidence/win_loss_ratio，采用上述稳健近似为最优方案。
    """
    n = len(merged)
    if n == 0:
        return {}
    raw: dict[str, float] = {}
    total = 0.0
    for ticker, info in merged.items():
        p = max(0.0, min(1.0, info.get("confidence", 0.5)))
        b = max(info.get("win_loss_ratio", 1.0), 0.001)
        f = p - (1.0 - p) / b
        if f <= 0:
            continue
        f = min(f, max_per_asset) * fraction
        if f <= 0:
            continue
        raw[ticker] = f
        total += f
    if not raw:
        return equal_weight(merged, n)
    if total > 1.0:
        # 总仓位超过 100% 时等比例缩减，保证不加杠杆
        return {t: w / total for t, w in raw.items()}
    # 总仓位 <= 100%：保持各标的分数凯利仓位，剩余为现金
    return raw
