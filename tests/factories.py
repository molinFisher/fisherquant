import polars as pl
import random
from datetime import date, timedelta


class DataFactory:
    def __init__(self, seed: int = 42):
        random.seed(seed)

    def generate_ohlcv(self, symbol: str, days: int = 252,
                       start_date: str = "2024-01-01",
                       trend: str = "random") -> pl.DataFrame:
        start = date.fromisoformat(start_date)
        dates = []
        d = start
        while len(dates) < days:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)

        close = 100.0
        data = {"date": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
        for dt in dates:
            daily_return = random.gauss(0.0005, 0.015)
            if trend == "bull":
                daily_return += 0.002
            elif trend == "bear":
                daily_return -= 0.002
            close *= (1 + daily_return)
            open_price = close * (1 + random.uniform(-0.005, 0.005))
            high = max(open_price, close) * (1 + random.uniform(0, 0.01))
            low = min(open_price, close) * (1 - random.uniform(0, 0.01))
            data["date"].append(dt.isoformat())
            data["open"].append(round(open_price, 2))
            data["high"].append(round(high, 2))
            data["low"].append(round(low, 2))
            data["close"].append(round(close, 2))
            data["volume"].append(random.randint(100000, 10000000))
        return pl.DataFrame(data)

    def generate_equity_curve(self, days: int = 252, annual_return: float = 0.15,
                              volatility: float = 0.20) -> list:
        daily_r = annual_return / 252
        daily_vol = volatility / (252 ** 0.5)
        curve = [1.0]
        for _ in range(days - 1):
            curve.append(curve[-1] * (1 + random.gauss(daily_r, daily_vol)))
        return curve
