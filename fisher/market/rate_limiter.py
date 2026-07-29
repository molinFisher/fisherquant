import time
import random
import threading
import asyncio
from functools import wraps
from ..config.schemas import RateLimitConfig
import logging

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """数据源限流（如东方财富 429 / Max retries exceed）时抛出的结构化异常。

    与普通的网络异常区分，便于上层把它归类为 ``reason="rate_limited"``
    并触发限流器降速自愈，而不是当作普通失败一刀切。
    """


# 限流特征关键词：命中任一即判定为"被数据源限流"（不区分大小写）
_RATE_LIMIT_SIGNATURES = (
    "max retries", "httpsconnectionpool", "429", "too many requests",
    "请求过于频繁", "freq", "rate limit", "ratelimited",
    "busy", "too frequent", "quota", "限流",
)


def is_rate_limit_error(exc: Exception) -> bool:
    """判断异常是否由数据源限流引起（覆盖多数据源文案，大小写不敏感）。"""
    msg = str(exc).lower()
    return any(sig in msg for sig in _RATE_LIMIT_SIGNATURES)


class RateLimiter:
    def __init__(self, max_per_minute: int = 20):
        self._max_per_minute = max_per_minute
        self._default_max = max_per_minute
        self._tokens: list[float] = []
        self._cool_until = 0.0  # 限流冷却截止时间戳
        self._lock = threading.Lock()

    def acquire(self):
        now = time.time()
        with self._lock:
            # 限流冷却：未到冷却时间则阻塞到冷却结束（自愈降速）
            if now < self._cool_until:
                sleep_time = self._cool_until - now
                logger.info("Rate limiter cooling down, sleep %.1fs", sleep_time)
                time.sleep(sleep_time)
                now = time.time()
            self._tokens = [t for t in self._tokens if t > now - 60]
            if len(self._tokens) >= self._max_per_minute:
                sleep_time = self._tokens[0] + 60 - now + random.uniform(0.1, 0.5)
                if sleep_time > 0:
                    logger.debug("Rate limit: sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)
            self._tokens.append(time.time())

    def cool_down(self, seconds: float = 30.0):
        """限流触发：追加冷却时长，让后续请求整体降速（自愈）。"""
        with self._lock:
            self._cool_until = max(self._cool_until, time.time() + seconds)
            self._tokens.clear()  # 清空令牌桶，迫使冷却期内请求排队
        logger.warning("Rate limiter cool_down %.1fs due to upstream throttling", seconds)

    def set_rate(self, max_per_minute: int):
        """临时调整速率（如"保守模式"降速）。仅改上限，不清空令牌。"""
        with self._lock:
            self._max_per_minute = max(1, int(max_per_minute))

    def reset_rate(self):
        """恢复默认速率。"""
        with self._lock:
            self._max_per_minute = self._default_max

    def reset(self):
        with self._lock:
            self._tokens.clear()
            self._cool_until = 0.0


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_error = None
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                            logger.warning(
                                "Retry %d/%d after %.1fs for %s: %s",
                                attempt + 1, max_retries, delay, func.__name__, e,
                            )
                            time.sleep(delay)
                raise last_error
            return async_wrapper
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_error = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                            logger.warning(
                                "Retry %d/%d after %.1fs for %s: %s",
                                attempt + 1, max_retries, delay, func.__name__, e,
                            )
                            time.sleep(delay)
                raise last_error
            return wrapper
    return decorator


_global_limiter = RateLimiter(max_per_minute=20)


def get_global_limiter() -> RateLimiter:
    return _global_limiter
