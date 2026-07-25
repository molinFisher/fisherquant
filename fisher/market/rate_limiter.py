import time
import random
import threading
import asyncio
from functools import wraps
from ..config.schemas import RateLimitConfig
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, max_per_minute: int = 20):
        self._max_per_minute = max_per_minute
        self._tokens: list[float] = []
        self._lock = threading.Lock()

    def acquire(self):
        now = time.time()
        with self._lock:
            self._tokens = [t for t in self._tokens if t > now - 60]
            if len(self._tokens) >= self._max_per_minute:
                sleep_time = self._tokens[0] + 60 - now + random.uniform(0.1, 0.5)
                if sleep_time > 0:
                    logger.debug("Rate limit: sleeping %.1fs", sleep_time)
                    time.sleep(sleep_time)
            self._tokens.append(time.time())

    def reset(self):
        with self._lock:
            self._tokens.clear()


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
