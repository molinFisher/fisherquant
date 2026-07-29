"""从配置构建 RiskEngine（对应 P0-5：让 risk.yaml 中的规则真正接入回测）。"""
import os
import logging
from .engine import RiskEngine
from .pre_trade import (
    MaxPositionRule,
    DailyLossLimitRule,
    PriceLimitRule,
    BlacklistRule,
    SectorLimitRule,
    MaxOrderQtyRule,
    MaxNotionalRule,
    MaxPositionPerSymbolRule,
    MaxLeverageRule,
    MaxOpenOrdersRule,
)

logger = logging.getLogger(__name__)

_RULE_CLASSES = {
    "MaxPosition": MaxPositionRule,
    "DailyLossLimit": DailyLossLimitRule,
    "PriceLimit": PriceLimitRule,
    "Blacklist": BlacklistRule,
    "SectorLimit": SectorLimitRule,
    "MaxOrderQty": MaxOrderQtyRule,
    "MaxNotional": MaxNotionalRule,
    "MaxPositionPerSymbol": MaxPositionPerSymbolRule,
    "MaxLeverage": MaxLeverageRule,
    "MaxOpenOrders": MaxOpenOrdersRule,
}


def build_risk_engine(config: dict | None) -> RiskEngine | None:
    """根据 risk.yaml 解析出的 dict 构建 RiskEngine。

    若无 pre_trade 规则则返回 None（表示不启用风险预检）。
    """
    if not config:
        return None
    pre_trade = config.get("pre_trade")
    if not pre_trade:
        return None

    blacklist = config.get("blacklist", []) or []
    rules = []
    for entry in pre_trade:
        name = entry.get("rule")
        cls = _RULE_CLASSES.get(name)
        if cls is None:
            logger.warning("Unknown risk rule: %s (skipped)", name)
            continue
        params = entry.get("params", {}) or {}
        # 全局参数注入
        if name == "Blacklist" and not params.get("blacklist"):
            params = dict(params)
            params["blacklist"] = blacklist
        try:
            rules.append(cls(**params))
        except TypeError:
            # 容忍参数不匹配：用默认构造
            rules.append(cls())
    if not rules:
        return None
    return RiskEngine(rules=rules)


def load_risk_config(path: str | None = None) -> dict | None:
    if path is None:
        # 默认读取项目 configs/risk.yaml（fisher/risk/ → 项目根需上两级）
        cand = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "risk.yaml")
        path = os.path.abspath(cand)
    if not os.path.exists(path):
        return None
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed; skipping risk config load")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load risk config %s: %s", path, e)
        return None
