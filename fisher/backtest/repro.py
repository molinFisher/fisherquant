"""可复现性支持（对应 P2-14）。

- 设置全局随机种子，确保回测可复现；
- 计算输入指纹（数据 + 参数哈希），用于审计与数据快照比对。
"""
import hashlib
import json
import random
from typing import Any

import polars as pl


def set_global_seed(seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except Exception:  # noqa: BLE001
        pass


def compute_input_hash(bars_fingerprint: str, strategy_config: dict, params: dict) -> str:
    """输入指纹：数据指纹 + 策略配置 + 运行参数，用于审计同一策略不同日期结果是否一致。"""
    payload = {
        "data": bars_fingerprint,
        "strategy": strategy_config,
        "params": params,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def bars_fingerprint(bars_df: pl.DataFrame) -> str:
    """数据快照指纹：基于标的数量、日期范围与收盘价聚合，粗略标识数据集版本。"""
    try:
        tickers = bars_df.select("ticker").unique().height
        dates = bars_df.select("trade_date").unique().sort("trade_date")
        n = dates.height
        first = dates["trade_date"][0] if n else "na"
        last = dates["trade_date"][n - 1] if n else "na"
        close_sum = float(bars_df.select("close").sum().item())
        return f"t{tickers}_d{n}_{first}_{last}_{close_sum:.2f}"
    except Exception:  # noqa: BLE001
        return "na"
