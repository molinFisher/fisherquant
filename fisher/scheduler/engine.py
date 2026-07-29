import logging
from collections import defaultdict
from datetime import datetime, time
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger(__name__)

MarketHook = Callable[[str], None]


class SchedulerEngine:
    def __init__(self, db_url: str = "sqlite:///data/scheduler.db"):
        # 仅使用进程内内存 jobstore：本应用所有任务均在启动时由 app.py 注册，
        # 无需跨重启持久化。若改用 SQLAlchemyJobStore 持久化，APScheduler 会在 add_job
        # 时 pickle 任务函数；而传入的 func 多为绑定方法
        # （svc.incremental_update / data_svc.refresh_symbol_dict），其持有的 DuckDB
        # 连接含不可序列化的 _thread.RLock，会抛 "cannot pickle '_thread.RLock' object"，
        # 导致全部定时任务注册失败。故忽略 db_url，固定使用默认内存 jobstore。
        scheduler_kwargs = {
            "executors": {"default": ThreadPoolExecutor(max_workers=4)},
            "job_defaults": {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            "timezone": "Asia/Shanghai",
        }
        self._scheduler = BackgroundScheduler(**scheduler_kwargs)
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
            except JobLookupError:
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

    def fire_market_open(self, market: str = "a_share") -> None:
        self._fire_market_hook("market_open", market)

    def fire_market_close(self, market: str = "a_share") -> None:
        self._fire_market_hook("market_close", market)

    def fire_mid_break(self, market: str = "a_share") -> None:
        self._fire_market_hook("mid_break", market)

    def fire_mid_resume(self, market: str = "a_share") -> None:
        self._fire_market_hook("mid_resume", market)

    @staticmethod
    def is_trading_now(market: str = "a_share") -> bool:
        now = datetime.now().time()
        weekday = datetime.now().weekday()
        if weekday >= 5:
            return False
        if market == "a_share":
            return (time(9, 30) <= now <= time(11, 30)) or (time(13, 0) <= now <= time(15, 0))
        elif market == "hk_connect":
            return (time(9, 30) <= now <= time(12, 0)) or (time(13, 0) <= now <= time(16, 0))
        return False

    def auto_schedule_market_hooks(self, market: str = "a_share"):
        self.add_job(
            "market_open_hook", lambda: self.fire_market_open(market),
            "cron", day_of_week="mon-fri", hour=9, minute=30,
        )
        self.add_job(
            "mid_break_hook", lambda: self.fire_mid_break(market),
            "cron", day_of_week="mon-fri", hour=11, minute=30,
        )
        self.add_job(
            "mid_resume_hook", lambda: self.fire_mid_resume(market),
            "cron", day_of_week="mon-fri", hour=13, minute=0,
        )
        self.add_job(
            "market_close_hook", lambda: self.fire_market_close(market),
            "cron", day_of_week="mon-fri", hour=15, minute=0,
        )
