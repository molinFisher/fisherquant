"""盘中实时快照刷新守护线程（PRD FR-7.6 / D-5，Task #16）。

设计要点：
- 进程内守护线程（非 Dash Interval），随应用常驻；由交易时段门控，非交易时段挂起，
  不空转轮询（避免非交易时段反复打 akshare 限频）。
- 刷新对象 = 自动加载宇宙（cache_catalog.auto_load_enabled = TRUE，FR-7.1/7.5），
  与 V1.3 自动加载线程共用 DuckDBManager 单写连接串行化，互不阻塞读连接。
- 快照写入复用 AutoLoadService.record_realtime_snapshot（同事务更新 catalog.realtime_ts，
  FR-1.2），保证「数据写了、目录也更新」。
- fetch 函数可注入（默认走 akshare 全市场 spot），便于单测用假数据验证门控/写入逻辑，
  不依赖真实网络（验收 15 同理）。
"""

import logging
import threading
from datetime import datetime, time as dtime
from typing import Callable, Optional

import akshare as ak

from .auto_load_service import AutoLoadService, market_from_ticker
from .cache_catalog_service import CacheCatalogService

logger = logging.getLogger(__name__)

# 默认轮询间隔（秒）：realtime_poll_min 默认 60 → 3600s；可由 config 覆盖
_DEFAULT_POLL_MIN = 60


def is_trading_hours(now: Optional[datetime] = None) -> bool:
    """A 股交易时段判定（与 quote_callbacks.check_trading_hours 同源口径）。

    日内：上午 9:15（含集合竞价）~ 11:30，下午 13:00 ~ 15:00；周末休市。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:  # 5=周六 6=周日
        return False
    t = now.time()
    if dtime(9, 15) <= t < dtime(11, 30):
        return True
    if dtime(13, 0) <= t < dtime(15, 0):
        return True
    return False


def _default_fetch(universe: set[str]) -> dict[str, tuple]:
    """默认实时快照拉取：akshare 全市场 A 股 spot。

    返回 dict: ticker -> (last_price, pre_close, change_pct, volume)。
    仅覆盖 A 股；港股实时快照不在本函数范围（看板降级日频，FR-6.2）。
    """
    out: dict[str, tuple] = {}
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        logger.warning("realtime spot fetch failed: %s", e)
        return out
    try:
        for _, r in df.iterrows():
            code = str(r["代码"]).zfill(6)
            ticker = f"{code}.SH" if code.startswith(("6", "5", "9")) else f"{code}.SZ"
            if ticker not in universe:
                continue
            out[ticker] = (
                float(r["最新价"]),
                float(r.get("昨收", 0) or 0),
                float(r["涨跌幅"]),
                float(r.get("成交量", 0) or 0),
            )
    except Exception as e:
        logger.warning("realtime spot parse failed: %s", e)
    return out


class RealtimeDaemon:
    """盘中实时快照守护线程（FR-7.6）。"""

    def __init__(
        self,
        auto_load_service: AutoLoadService,
        interval: int = _DEFAULT_POLL_MIN * 60,
        fetch_fn: Optional[Callable[[set[str]], dict[str, tuple]]] = None,
        catalog: Optional[CacheCatalogService] = None,
    ):
        self._svc = auto_load_service
        self._db = auto_load_service._db
        self._catalog = catalog or auto_load_service._catalog
        self._interval = interval
        self._fetch_fn = fetch_fn or _default_fetch
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # 限频安全重试（FR-7.4）：fetch 失败时按退避重试，全失败则该轮跳过，
        # 不写 cache_catalog（无 FALSE→TRUE 误标）。次数/退避可注入（CI 用 [0,0,0] 加速）。
        self._retry_max_attempts = 3
        self._retry_backoff = [2, 5, 15]

    def _fetch_with_retry(self, universe) -> dict[str, tuple]:
        """限频安全重试（FR-7.4）：fetch 异常（限频/超时）→ 按退避重试，全失败则抛出跳过该轮。

        退避等待经由 self._stop.wait(backoff) 实现：暂停/停止信号在退避期间抵达即放弃本轮，
        避免守护线程在退避中无法及时响应停止（不阻塞主流程）。
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._retry_max_attempts):
            try:
                return self._fetch_fn(universe)
            except Exception as e:  # 限频/超时等网络异常
                last_err = e
                if attempt < self._retry_max_attempts - 1:
                    backoff = self._retry_backoff[min(attempt, len(self._retry_backoff) - 1)]
                    if backoff > 0 and self._stop.wait(backoff):
                        # 退避期间被暂停/停止 → 立即放弃本轮
                        raise InterruptedError("interrupted during backoff")
        if last_err is not None:
            raise last_err
        return {}

    def tick(self, now: Optional[datetime] = None) -> dict:
        """执行一轮快照刷新。非交易时段 / 宇宙为空 → 跳过（不报错、不空转）。

        限频/超时（FR-7.4）：经 _fetch_with_retry 退避重试后仍失败 → 该轮跳过，
        绝不写 cache_catalog（无 FALSE→TRUE 误标），日线/分钟补齐主流程（独立线程/任务）不受影响。
        """
        if not is_trading_hours(now):
            return {"skipped": True, "reason": "non_trading"}
        universe = set(self._catalog.get_auto_load_universe())
        if not universe:
            return {"skipped": True, "reason": "empty_universe"}
        try:
            snaps = self._fetch_with_retry(universe)
        except InterruptedError:
            return {"skipped": True, "reason": "interrupted"}
        except Exception as e:
            logger.warning("realtime fetch failed after retries: %s", e)
            return {"skipped": True, "reason": "fetch_error", "error": str(e)[:120]}
        written = 0
        ts = datetime.now()
        for ticker, (last, pre, pct, vol) in snaps.items():
            try:
                market = market_from_ticker(ticker)
                self._svc.record_realtime_snapshot(
                    ticker, market, last, pre, pct, ts)
                written += 1
            except Exception as e:
                logger.warning("snapshot write failed %s: %s", ticker, e)
        logger.info("realtime_daemon_tick universe=%d written=%d", len(universe), written)
        return {"skipped": False, "universe": len(universe), "written": written}

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.warning("realtime daemon tick error: %s", e)
            self._stop.wait(self._interval)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="realtime-daemon")
        self._thread.start()
        logger.info("realtime daemon started (interval=%ds)", self._interval)

    def stop(self):
        self._stop.set()
        self._thread = None
