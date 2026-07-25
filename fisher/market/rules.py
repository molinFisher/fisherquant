# fisher/market/rules.py
from abc import ABC, abstractmethod


class ExchangeRules(ABC):
    @property
    @abstractmethod
    def t_plus(self) -> int: ...

    @abstractmethod
    def lot_size(self, ticker: str) -> int: ...

    @abstractmethod
    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]: ...

    @abstractmethod
    def trading_sessions(self) -> list[tuple[str, str]]: ...

    @property
    @abstractmethod
    def stamp_duty(self) -> float: ...

    @property
    @abstractmethod
    def stamp_duty_side(self) -> str: ...


class AShareRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 1

    def lot_size(self, ticker: str) -> int:
        return 100

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        if ticker.startswith("688"):
            rate = 0.20
        elif ticker.startswith("300") or ticker.startswith("301"):
            rate = 0.20
        elif ticker.startswith("8"):
            rate = 0.30
        elif "ST" in ticker.upper() or "*ST" in ticker.upper():
            rate = 0.05
        else:
            rate = 0.10
        return round(price * (1 + rate), 2), max(round(price * (1 - rate), 2), 0.01)

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [
            ("09:30", "11:30"),
            ("13:00", "15:00"),
        ]

    @property
    def stamp_duty(self) -> float:
        return 0.0005

    @property
    def stamp_duty_side(self) -> str:
        return "sell"


class HKConnectRules(ExchangeRules):
    _LOTS = {"00700": 100, "09988": 100, "01810": 200}

    @property
    def t_plus(self) -> int:
        return 0

    def lot_size(self, ticker: str) -> int:
        code = ticker.split(".")[0] if "." in ticker else ticker
        return self._LOTS.get(code, 100)

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        return float("inf"), 0.0

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [
            ("09:30", "12:00"),
            ("13:00", "16:00"),
        ]

    @property
    def stamp_duty(self) -> float:
        return 0.001

    @property
    def stamp_duty_side(self) -> str:
        return "both"


class ETFRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 1

    def lot_size(self, ticker: str) -> int:
        return 100

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        rate = 0.10
        return round(price * (1 + rate), 2), max(round(price * (1 - rate), 2), 0.01)

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [("09:30", "11:30"), ("13:00", "15:00")]

    @property
    def stamp_duty(self) -> float:
        return 0.0

    @property
    def stamp_duty_side(self) -> str:
        return "none"


class CBRules(ExchangeRules):
    @property
    def t_plus(self) -> int:
        return 0

    def lot_size(self, ticker: str) -> int:
        return 10

    def price_limits(self, price: float, ticker: str = "") -> tuple[float, float]:
        return float("inf"), 0.0

    def trading_sessions(self) -> list[tuple[str, str]]:
        return [("09:30", "11:30"), ("13:00", "15:00")]

    @property
    def stamp_duty(self) -> float:
        return 0.0

    @property
    def stamp_duty_side(self) -> str:
        return "none"


def get_rules(market: str) -> ExchangeRules:
    rules_map = {
        "a_share": AShareRules,
        "hk_connect": HKConnectRules,
        "etf": ETFRules,
        "convertible_bond": CBRules,
    }
    cls = rules_map.get(market)
    if cls is None:
        raise ValueError(f"Unknown market: {market}")
    return cls()
