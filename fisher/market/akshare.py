# fisher/market/akshare.py
import asyncio
import logging
import traceback
import akshare as ak
from .gateway import MarketGateway
from .model import Bar
from .rate_limiter import get_global_limiter, retry_with_backoff
from .ticker import resolve_ticker
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
                start_date=start, end_date=end, adjust="",
            )
            return self._df_to_bars(df, ticker)
        else:
            # P2-12：尽力接入分钟线（akshare 免费接口不稳定，失败则降级为空并告警）
            return await self._fetch_minute_bars(code, frequency)

    async def _fetch_minute_bars(self, code: str, frequency: str) -> list:
        period_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}
        period = period_map.get(frequency, "5")
        prefix = "sh" if code.startswith(("6", "5", "9")) else "sz"
        try:
            df = await asyncio.to_thread(ak.stock_zh_a_minute, symbol=f"{prefix}{code}", period=period, adjust="")
            if df is None or df.empty:
                logger.warning("Minute bars empty for %s", code)
                return []
            bars = []
            for _, row in df.iterrows():
                trade_date = str(row.get("datetime", ""))[:10]
                bars.append(Bar(
                    ticker=self._normalize_ticker(code, ""),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row.get("volume", 0)),
                    amount=float(row.get("amount", 0.0)),
                    frequency=frequency,
                    trade_date=trade_date,
                ))
            return bars
        except Exception as e:  # noqa: BLE001
            logger.warning("Minute bars not available (akshare free tier): %s", e)
            return []

    def _parse_ticker(self, ticker: str) -> tuple[str, str]:
        parts = ticker.split(".")
        if len(parts) == 2:
            return parts[0], parts[1].lower()
        return ticker, ""

    def _normalize_ticker(self, code: str, market: str) -> str:
        # 统一走幂等 resolve_ticker，避免双后缀 / .UNKNOWN 脏数据
        return resolve_ticker(code, market)

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
