import logging
import time
import sys
from typing import Callable

logger = logging.getLogger(__name__)

Callback = Callable[[dict], None]


class ConsoleChannel:
    def send(self, event_type: str, event: dict) -> None:
        msg = event.get("message", str(event))
        print(f"[{event_type}] {msg}", file=sys.stderr)


class AlertService:
    def __init__(self, throttle_seconds: float = 60.0):
        self._subscribers: dict[str, list[Callback]] = {}
        self._throttle_seconds = throttle_seconds
        self._last_notify: dict[str, float] = {}

    def subscribe(self, event_type: str, callback: Callback) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callback) -> None:
        if event_type in self._subscribers:
            subs = self._subscribers[event_type]
            if callback in subs:
                subs.remove(callback)

    def notify(self, event_type: str, event: dict) -> None:
        now = time.time()
        last = self._last_notify.get(event_type, 0.0)
        if now - last < self._throttle_seconds:
            return
        self._last_notify[event_type] = now

        for callback in self._subscribers.get(event_type, []):
            try:
                callback(event)
            except Exception:
                logger.exception("Alert callback for event %s raised exception", event_type)
