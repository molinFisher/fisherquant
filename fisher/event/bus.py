import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from collections import defaultdict
from .types import Event
from ..config.schemas import EventConfig

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus(ABC):
    @abstractmethod
    def subscribe(self, event_type: str, handler: Handler) -> None: ...

    @abstractmethod
    def unsubscribe(self, event_type: str, handler: Handler) -> None: ...

    @abstractmethod
    def publish(self, event: Event) -> None: ...


class AsyncioEventBus(EventBus):
    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        event_type = event.__event_type__
        for handler in self._handlers.get(event_type, []):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is None:
                logger.warning(
                    "No running event loop, cannot schedule handler for %s",
                    event_type,
                )
                continue
            asyncio.create_task(self._safe_call(handler, event))

    async def _safe_call(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Handler for event %s raised exception",
                event.__event_type__,
            )


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str):
        raise NotImplementedError("Redis event bus not yet implemented")

    def subscribe(self, event_type: str, handler: Handler) -> None:
        raise NotImplementedError

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        raise NotImplementedError

    def publish(self, event: Event) -> None:
        raise NotImplementedError


def create_event_bus(cfg: EventConfig) -> EventBus:
    if cfg.backend == "redis":
        return RedisEventBus(cfg.redis_url or "")
    return AsyncioEventBus()
