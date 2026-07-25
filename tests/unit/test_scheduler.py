import pytest
from datetime import time
from fisher.scheduler.engine import SchedulerEngine


class TestSchedulerEngine:
    def test_init(self):
        engine = SchedulerEngine()
        assert engine is not None

    def test_add_job(self):
        engine = SchedulerEngine()
        calls = []

        def task():
            calls.append(1)

        engine.add_job("test_job", task, "cron", hour=9, minute=30)
        assert "test_job" in engine._jobs

    def test_add_daily_task(self):
        engine = SchedulerEngine()
        calls = []

        def task():
            calls.append(1)

        engine.add_daily_task("daily", task, time(16, 0))
        assert "daily" in engine._jobs

    def test_add_periodic_task(self):
        engine = SchedulerEngine()
        calls = []

        def task():
            calls.append(1)

        engine.add_periodic_task("periodic", task, interval_minutes=60)
        assert "periodic" in engine._jobs

    def test_remove_job(self):
        engine = SchedulerEngine()
        calls = []

        def task():
            calls.append(1)

        engine.add_job("temp", task, "cron", hour=9, minute=30)
        engine.remove_job("temp")
        assert "temp" not in engine._jobs

    def test_market_open_hook(self):
        engine = SchedulerEngine()
        calls = []

        def on_open(market):
            calls.append(market)

        engine.on_market_open(on_open)
        engine._fire_market_hook("market_open", "a_share")
        assert len(calls) == 1
        assert calls[0] == "a_share"

    def test_market_close_hook(self):
        engine = SchedulerEngine()
        calls = []

        def on_close(market):
            calls.append(market)

        engine.on_market_close(on_close)
        engine._fire_market_hook("market_close", "a_share")
        assert len(calls) == 1

    def test_mid_break_hook(self):
        engine = SchedulerEngine()
        calls = []

        def on_break(market):
            calls.append(market)

        engine.on_mid_break(on_break)
        engine._fire_market_hook("mid_break", "a_share")
        assert len(calls) == 1

    def test_mid_resume_hook(self):
        engine = SchedulerEngine()
        calls = []

        def on_resume(market):
            calls.append(market)

        engine.on_mid_resume(on_resume)
        engine._fire_market_hook("mid_resume", "hk_connect")
        assert len(calls) == 1

    def test_multiple_hooks(self):
        engine = SchedulerEngine()
        r1, r2 = [], []

        def h1(m): r1.append(m)
        def h2(m): r2.append(m)

        engine.on_market_open(h1)
        engine.on_market_open(h2)
        engine._fire_market_hook("market_open", "a_share")
        assert len(r1) == 1
        assert len(r2) == 1

    def test_exception_in_hook_isolated(self):
        engine = SchedulerEngine()
        r2 = []

        def bad(m): raise RuntimeError("crash")
        def good(m): r2.append(m)

        engine.on_market_open(bad)
        engine.on_market_open(good)
        engine._fire_market_hook("market_open", "a_share")
        assert len(r2) == 1
