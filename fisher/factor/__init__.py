from .base import Factor
from .registry import FactorRegistry
from .technical import MACD, RSI14, BollingerBands
from .price import (
    Momentum20D,
    Momentum60D,
    Volatility20D,
    Volatility60D,
    Turnover5D,
    Turnover20D,
    VolumeRatio,
)
from .volatility import Atr

# 已实现且可注册的因子类（与 fisher/factor 下各模块中的 Factor 子类保持一致）
_REGISTER_FACTOR_CLASSES = (
    MACD,
    RSI14,
    BollingerBands,
    Momentum20D,
    Momentum60D,
    Volatility20D,
    Volatility60D,
    Turnover5D,
    Turnover20D,
    VolumeRatio,
    Atr,
)

_REGISTERED = False


def register_all_factors() -> None:
    """注册全部已实现因子到 FactorRegistry（幂等）。

    在应用启动（app.layout 构建之前）调用一次，打通因子中心计算链路。
    """
    global _REGISTERED
    if _REGISTERED:
        return
    for factor_cls in _REGISTER_FACTOR_CLASSES:
        FactorRegistry.register(factor_cls())
    _REGISTERED = True


__all__ = [
    "Factor",
    "FactorRegistry",
    "register_all_factors",
    "MACD",
    "RSI14",
    "BollingerBands",
    "Momentum20D",
    "Momentum60D",
    "Volatility20D",
    "Volatility60D",
    "Turnover5D",
    "Turnover20D",
    "VolumeRatio",
    "Atr",
]
