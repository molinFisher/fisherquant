# fisher/market/akshare.py
import logging
import akshare as ak
from .gateway import MarketGateway
from .model import Bar
from ..config.schemas import MarketConfig

logger = logging.getLogger(__name__)


class AkshareAdapter(MarketGateway):
    def __init__(self, cfg: MarketConfig):
        super().__init__()
        self.source = "akshare"
        self._subscribed: list[str] = []
        self._refresh_cfg = cfg.refresh

    async def _run(self):
        logger.info("AkshareAdapter started")

    async def _stop(self):
        logger.info("AkshareAdapter stopped")
        self._subscribed.clear()

    async def subscribe(self, tickers: list[str]):
        for t in tickers:
            if t not in self._subscribed:
                self._subscribed.append(t)
        logger.info("Subscribed to %d tickers", len(self._subscribed))

    async def get_bars(self, ticker: str, start: str, end: str, frequency: str = "1d"):
        try:
            code, market = self._parse_ticker(ticker)
            if frequency == "1d":
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start, end_date=end, adjust="qfq"
                )
                return self._df_to_bars(df, ticker)
            else:
                logger.warning("Minute bars not supported by akshare free tier")
                return []
        except Exception as e:
            logger.error("Failed to fetch bars for %s: %s", ticker, e)
            return []

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        parts = ticker.split(".")
        if len(parts) == 2:
            return parts[0], parts[1].lower()
        return ticker, ""

    def _normalize_ticker(self, code: str, market: str) -> str:
        if market == "a_share":
            if code.startswith(("6", "5", "9")):
                return f"{code}.SH"
            return f"{code}.SZ"
        elif market == "hk_connect":
            code_fixed = code.zfill(5)
            return f"{code_fixed}.HK"
        return f"{code}.UNKNOWN"

    def _df_to_bars(self, df, ticker: str) -> list[Bar]:
        if df is None or df.empty:
            return []
        bars = []
        for _, row in df.iterrows():
            trade_date = str(row.get("日期", ""))[:10]
            bars.append(Bar(
                ticker=ticker,
                open=float(row["开盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                close=float(row["收盘"]),
                volume=int(row["成交量"]),
                amount=float(row["成交额"]),
                frequency="1d",
                trade_date=trade_date,
            ))
        return bars
