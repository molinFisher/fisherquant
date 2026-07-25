import akshare as ak
import polars as pl
from datetime import date
from fisher.store.engine import DuckDBEngine
from fisher.store.repository import BarRepo
from fisher.market.model import Bar
from fisher.market.rules import get_rules
import logging

logger = logging.getLogger(__name__)

A_SHARE_TICKERS = [
    "000001.SZ", "000002.SZ", "000858.SZ", "002415.SZ", "300750.SZ",
    "600000.SH", "600036.SH", "600276.SH", "600519.SH", "000333.SZ",
    "002594.SZ", "300059.SZ", "600900.SH", "601318.SH", "000725.SZ",
    "600887.SH", "601166.SH", "600585.SH", "002475.SZ", "300124.SZ",
]

HK_CONNECT_TICKERS = [
    "00700.HK", "03690.HK", "01810.HK", "09988.HK", "01211.HK",
]


class DataDownloader:
    def __init__(self, engine: DuckDBEngine):
        self.engine = engine

    def download_all(self) -> dict:
        result = {"a_share": [], "hk_connect": [], "errors": []}
        for t in A_SHARE_TICKERS:
            try:
                bars = self.download_a_share(t, "2024-01-01", "2024-12-31")
                if bars:
                    self._save_bars(bars)
                    result["a_share"].append(t)
            except Exception as e:
                result["errors"].append(f"A-share {t}: {e}")
                logger.error("A-share %s failed: %s", t, e)
        for t in HK_CONNECT_TICKERS:
            try:
                bars = self.download_hk_connect(t, "2024-01-01", "2024-12-31")
                if bars:
                    self._save_bars(bars)
                    result["hk_connect"].append(t)
            except Exception as e:
                result["errors"].append(f"HK {t}: {e}")
                logger.error("HK %s failed: %s", t, e)
        return result

    def download_a_share(self, ticker: str, start: str, end: str) -> list[Bar]:
        code, _ = self._parse_ticker(ticker)
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
        if df is None or df.empty:
            return []
        return self._df_to_bars(df, ticker, "a_share")

    def download_hk_connect(self, ticker: str, start: str, end: str) -> list[Bar]:
        code, _ = self._parse_ticker(ticker)
        df = ak.stock_hk_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
        if df is None or df.empty:
            return []
        return self._df_to_bars(df, ticker, "hk_connect")

    def validate_data(self, ticker: str) -> dict:
        bars = BarRepo.get_bars_daily(self.engine, [ticker], "2024-01-01", "2024-12-31")
        df = pl.DataFrame(bars) if isinstance(bars, list) else bars
        n = len(df)
        result = {
            "ticker": ticker,
            "total_bars": n,
            "valid": True,
            "issues": [],
        }
        if n < 200:
            result["issues"].append(f"Only {n} bars (expect >= 200)")
            result["valid"] = False
        if "close" in df.columns:
            if df["close"].min() <= 0:
                result["issues"].append("close price <= 0")
                result["valid"] = False
        return result

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        parts = ticker.split(".")
        return (parts[0], parts[1].lower()) if len(parts) == 2 else (ticker, "")

    def _df_to_bars(self, df, ticker: str, market: str) -> list[Bar]:
        bars = []
        for _, row in df.iterrows():
            trade_date = str(row.get("日期", ""))[:10]
            bars.append(Bar(
                ticker=ticker, market=market, frequency="1d",
                open=float(row["开盘"]), high=float(row["最高"]),
                low=float(row["最低"]), close=float(row["收盘"]),
                volume=int(row["成交量"]), amount=float(row["成交额"]),
                trade_date=trade_date,
            ))
        return bars

    def _save_bars(self, bars: list[Bar]):
        if not bars:
            return
        rows = [b.to_dict() for b in bars]
        df = pl.DataFrame(rows)
        BarRepo.save_bars_daily(self.engine, df)
