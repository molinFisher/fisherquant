import re
from dataclasses import dataclass, field
from typing import Optional

EXCHANGE_MAP = {
    "6": ".SH", "5": ".SH", "9": ".SH",
    "0": ".SZ", "3": ".SZ", "2": ".SZ", "8": ".BJ",
}


def resolve_ticker(code: str, market: str = "a_share") -> str:
    if market == "hk_connect":
        return f"{code.zfill(5)}.HK"
    prefix = code[0] if code else ""
    suffix = EXCHANGE_MAP.get(prefix, ".UNKNOWN")
    return f"{code}{suffix}"


TYPE_MAP = {
    "sma_cross": "SMA 交叉", "macd": "MACD",
    "bollinger": "布林带", "rsi": "RSI",
    "buy_and_hold": "买入持有", "custom": "自定义 DSL",
}

STRATEGY_PARAM_SCHEMAS = {
    "sma_cross": {"fast": {"default": 5, "min": 1, "max": 252, "label": "快线周期"},
                  "slow": {"default": 20, "min": 2, "max": 504, "label": "慢线周期"}},
    "macd": {"fast": {"default": 12, "min": 1, "max": 252, "label": "快线"},
             "slow": {"default": 26, "min": 2, "max": 504, "label": "慢线"},
             "signal": {"default": 9, "min": 1, "max": 252, "label": "信号线"}},
    "bollinger": {"period": {"default": 20, "min": 2, "max": 252, "label": "周期"},
                  "std": {"default": 2.0, "min": 0.5, "max": 5.0, "label": "标准差倍数"}},
    "rsi": {"period": {"default": 14, "min": 2, "max": 252, "label": "周期"},
            "overbought": {"default": 70, "min": 50, "max": 100, "label": "超买阈值"},
            "oversold": {"default": 30, "min": 0, "max": 50, "label": "超卖阈值"}},
    "buy_and_hold": {},
    "custom": {"dsl_config": {"default": {}, "label": "DSL 配置"}},
}


@dataclass
class StrategyConfig:
    name: str
    type: str
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    enabled: bool = True

    def validate(self) -> list[str]:
        errors = []
        if not self.name or not self.name.strip():
            errors.append("策略名称不能为空")
        if self.type not in TYPE_MAP:
            errors.append(f"未知策略类型: {self.type}")
        if self.type == "custom" and not self.params.get("dsl_config"):
            errors.append("自定义策略必须配置 DSL")
        return errors

    @property
    def safe_filename(self) -> str:
        return re.sub(r'[^\w\-]', '_', self.name)


@dataclass
class WizardState:
    step: int = 0
    name: str = ""
    type: str = ""
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    editing: bool = False
    original_name: str = ""


AUTO_LOAD_CFG = {
    "enabled": True,
    "initial_universe": "both",
    "initial_start": "2024-01-01",
    "initial_batch_size": 5,
    "initial_batch_interval": 15,
    "incremental_batch_size": 20,
    "incremental_batch_interval": 10,
    "incremental_time": "16:30",
}
