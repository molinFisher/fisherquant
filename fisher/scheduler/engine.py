import logging
from collections import defaultdict
from datetime import time
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

MarketHook = Callable[[str], None]


class SchedulerEngine:
    def __init__(self):
        self._scheduler = BackgroundScheduler()
        self._jobs: dict[str, dict] = {}
        self._hooks: dict[str, list[MarketHook]] = defaultdict(list)

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def add_job(
        self,
        name: str,
        func: Callable,
        trigger: str,
        **kwargs,
    ) -> None:
        if trigger == "cron":
            t = CronTrigger(**kwargs)
        elif trigger == "interval":
            t = IntervalTrigger(**kwargs)
        else:
            raise ValueError(f"Unknown trigger: {trigger}")

        job = self._scheduler.add_job(func, trigger=t, name=name)
        self._jobs[name] = {"job": job, "func": func}

    def add_daily_task(self, name: str, func: Callable, at_time: time) -> None:
        self.add_job(
            name, func, "cron",
            hour=at_time.hour,
            minute=at_time.minute,
        )

    def add_periodic_task(
        self,
        name: str,
        func: Callable,
        interval_minutes: int = 60,
    ) -> None:
        self.add_job(
            name, func, "interval",
            minutes=interval_minutes,
        )

    def remove_job(self, name: str) -> None:
        if name in self._jobs:
            job_info = self._jobs.pop(name)
            try:
                job_info["job"].remove()
            except Exception:
                pass

    def on_market_open(self, callback: MarketHook) -> None:
        self._hooks["market_open"].append(callback)

    def on_market_close(self, callback: MarketHook) -> None:
        self._hooks["market_close"].append(callback)

    def on_mid_break(self, callback: MarketHook) -> None:
        self._hooks["mid_break"].append(callback)

    def on_mid_resume(self, callback: MarketHook) -> None:
        self._hooks["mid_resume"].append(callback)

    def _fire_market_hook(self, hook_name: str, market: str) -> None:
        for callback in self._hooks.get(hook_name, []):
            try:
                callback(market)
            except Exception:
                logger.exception("Error in market hook '%s'", hook_name)
