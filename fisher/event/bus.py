import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from collections import defaultdict, deque
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
        self._handler_set: dict[str, set[int]] = defaultdict(set)
        self._tasks: set[asyncio.Task] = set()
        self._sync_queue: deque = deque()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        hid = id(handler)
        if hid not in self._handler_set[event_type]:
            self._handler_set[event_type].add(hid)
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        hid = id(handler)
        if hid in self._handler_set[event_type]:
            self._handler_set[event_type].discard(hid)
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        event_type = event.__event_type__
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "publish() called from non-async context. "
                "Use publish_sync() for synchronous callers."
            )
        for handler in self._handlers.get(event_type, []):
            task = asyncio.create_task(self._safe_call(handler, event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def publish_sync(self, event: Event) -> None:
        self._sync_queue.append(event)

    def drain_sync(self) -> list[Event]:
        events = list(self._sync_queue)
        self._sync_queue.clear()
        return events

    async def _safe_call(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Handler for event %s raised exception",
                event.__event_type__,
            )

    async def flush(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


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
