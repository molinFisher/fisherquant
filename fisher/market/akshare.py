# fisher/market/akshare.py
import asyncio
import logging
import traceback
import akshare as ak
from .gateway import MarketGateway
from .model import Bar
from .rate_limiter import get_global_limiter, retry_with_backoff
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
            return await self._fetch_bars(ticker, start, end, frequency)
        except Exception:
            logger.error("Failed to fetch bars for %s:\n%s", ticker, traceback.format_exc())
            return []

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def _fetch_bars(self, ticker: str, start: str, end: str, frequency: str = "1d"):
        get_global_limiter().acquire()
        code, market = self._parse_ticker(ticker)
        if frequency == "1d":
            df = await asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq",
            )
            return self._df_to_bars(df, ticker)
        else:
            logger.warning("Minute bars not supported by akshare free tier")
            return []

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        parts = ticker.split(".")
        if len(parts) == 2:
            return parts[0], parts[1].lower()
        return ticker, ""

    _NORMALIZE_PREFIX_MAP: dict[str, str] = {
        "000": "SZ", "001": "SZ", "002": "SZ", "003": "SZ",
        "600": "SH", "601": "SH", "603": "SH", "605": "SH",
        "688": "SH",
        "300": "SZ", "301": "SZ",
        "200": "SZ",  # B-share SZ
        "900": "SH",  # B-share SH
        "400": "BJ", "430": "BJ",
        "830": "BJ", "831": "BJ", "832": "BJ", "833": "BJ", "834": "BJ",
        "835": "BJ", "836": "BJ", "837": "BJ", "838": "BJ", "839": "BJ",
        "870": "BJ", "871": "BJ", "872": "BJ", "873": "BJ",
    }

    def _normalize_ticker(self, code: str, market: str) -> str:
        if market == "a_share":
            for prefix, exchange in self._NORMALIZE_PREFIX_MAP.items():
                if code.startswith(prefix):
                    return f"{code}.{exchange}"
            if code.startswith("5"):
                return f"{code}.SH"
            if code.startswith(("0", "2", "3", "4", "8")):
                return f"{code}.SZ"
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
