import time
import logging

from fisher.dash_app.services.auto_load_service import (
    AutoLoadService, STATUS_FAILED, PHASE_DONE,
)


class _MockDF:
    def __init__(self, data):
        self._data = data
        self.columns = list(data[0].keys()) if data else []

    def iterrows(self):
        for i, row in enumerate(self._data):
            yield i, row

    @property
    def empty(self):
        return len(self._data) == 0


def _wait(svc, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = svc.get_state()
        alive = svc._thread is not None and svc._thread.is_alive()
        if st["phase"] == PHASE_DONE and not alive:
            return
        time.sleep(0.02)


class TestRetryQueue:
    def test_eventual_failure_after_retries(self, auto_load_service, monkeypatch):
        """FR-4.2：≤3 轮重试后，单只标的 attempts 达上限并进入失败清单（退避可注入为 0 加速）。"""
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        svc._retry_max_attempts = 3
        universe = svc._snapshot_universe()
        assert universe, "mock universe must be non-empty"
        failing = set(universe[:2])

        def fake(ticker, market, plan, gap_start):
            if ticker in failing:
                raise RuntimeError("simulated network timeout")
            return []

        monkeypatch.setattr(svc, "_download", fake)
        svc.start_session()
        _wait(svc)
        st = svc.get_state()
        assert st["failed"] == 2
        failed = svc.get_failed()
        assert len(failed) == 2
        for f in failed:
            assert f["attempts"] == 3
            assert f["reason"] == "请求超时"

    def test_get_failed_uses_symbol_dict(self, auto_load_service, monkeypatch):
        """FR-4.3 / U-5：失败清单名称来自 symbol_dict LEFT JOIN，缺失显示 '—'。"""
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        svc._retry_max_attempts = 1
        universe = svc._snapshot_universe()
        assert universe
        failing = set(universe[:1])
        t = next(iter(failing))
        svc._db.execute(
            "INSERT OR REPLACE INTO symbol_dict (ticker,code,name,market) VALUES (?,?,?,?)",
            [t, t.split('.')[0], "测试股", "a_share"])

        def fake(ticker, market, plan, gap_start):
            if ticker in failing:
                raise RuntimeError("connect timeout")
            return []

        monkeypatch.setattr(svc, "_download", fake)
        svc.start_session()
        _wait(svc)
        failed = svc.get_failed()
        assert any(f["ticker"] == t and f["name"] == "测试股" for f in failed)

    def test_manual_retry_failed_recovers(self, auto_load_service, monkeypatch):
        """FR-4.3：最终失败项可通过「重试失败项」按钮再次尝试并成功（attempts 重置）。"""
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        svc._retry_max_attempts = 1
        universe = svc._snapshot_universe()
        assert universe
        failing = set(universe[:1])

        def fail_once(ticker, market, plan, gap_start):
            if ticker in failing:
                raise RuntimeError("connect timeout")
            return []

        monkeypatch.setattr(svc, "_download", fail_once)
        svc.start_session()
        _wait(svc)
        assert svc.get_state()["failed"] == 1
        assert svc.get_failed()[0]["attempts"] == 1
        # 手动重试，这次成功
        monkeypatch.setattr(svc, "_download", lambda ticker, m, p, g: [])
        svc.retry_failed()
        _wait(svc)
        assert svc.get_state()["failed"] == 0

    def test_retry_respects_limiter(self, auto_load_service, monkeypatch):
        """FR-4.4：重试路径同样走 _download → 受限频器约束。"""
        import akshare as ak
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        svc._retry_max_attempts = 2
        universe = svc._snapshot_universe()
        assert universe
        bad = universe[0]
        bad_code = bad.split('.')[0]

        def bad_daily(symbol=None, start_date="", end_date="", adjust=""):
            if bad_code in (symbol or ""):
                raise RuntimeError("connect timeout")
            return _MockDF([
                {"date": "2024-01-02", "open": 1, "high": 1, "low": 1, "close": 1,
                 "volume": 1, "amount": 1.0},
            ])

        monkeypatch.setattr(ak, "stock_zh_a_daily", bad_daily)
        calls = {"n": 0}
        orig = svc._limiter.acquire

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        monkeypatch.setattr(svc._limiter, "acquire", counting)
        svc.start_session()
        _wait(svc)
        assert calls["n"] > 0  # 重试仍走 _download，因此受限频
        assert svc.get_state()["failed"] >= 1


class TestBuriedPoints:
    def test_core_events_logged(self, auto_load_service, monkeypatch, caplog):
        """FR-6.6：§8 埋点事件以 logger.info 结构化落地，caplog 可断言。"""
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        svc._retry_max_attempts = 1
        universe = svc._snapshot_universe()
        assert universe
        failing = set(universe[:1])

        def fake(ticker, market, plan, gap_start):
            if ticker in failing:
                raise RuntimeError("connection timeout")
            return []

        monkeypatch.setattr(svc, "_download", fake)
        caplog.set_level(logging.INFO)
        svc.start_session()
        _wait(svc)
        svc.pause()
        logs = caplog.text
        assert "load_plan_generated" in logs
        assert "load_symbol_failed" in logs
        assert "load_session_done" in logs
        assert "load_paused" in logs

    def test_resume_logged(self, auto_load_service, monkeypatch, caplog):
        svc = auto_load_service
        svc._retry_backoff = [0, 0, 0]
        monkeypatch.setattr(svc, "_download", lambda ticker, m, p, g: [])
        caplog.set_level(logging.INFO)
        svc.start_session()
        _wait(svc)
        svc.resume_session()
        assert "load_resumed" in caplog.text
