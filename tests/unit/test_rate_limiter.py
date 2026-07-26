"""RateLimiter 限流计数与窗口测试（P2 低覆盖补齐）。

RateLimiter 使用 60 秒滚动窗口 + 最大配额。acquire 在窗口内调用：
- 若窗口内计数 >= max_per_minute，则 time.sleep 直到最早令牌过期；
- 否则记录令牌并立即返回。

为不引入真实 60s 等待，使用可控时钟（monkeypatch time.time / time.sleep）。
"""
import threading
import pytest
import fisher.market.rate_limiter as rl


class FakeClock:
    """可控时钟：time.time 返回 self.now，time.sleep 记录并推进 now。"""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


def _patch_time(monkeypatch, clock):
    monkeypatch.setattr(rl.time, "time", clock.time)
    monkeypatch.setattr(rl.time, "sleep", clock.sleep)


class TestRateLimiterLimit:
    def test_acquire_under_limit_no_sleep(self, monkeypatch, clock):
        _patch_time(monkeypatch, clock)
        limiter = rl.RateLimiter(max_per_minute=3)
        for _ in range(3):
            limiter.acquire()
        assert clock.sleeps == []  # 未超配额，不阻塞
        assert len(limiter._tokens) == 3

    def test_acquire_over_limit_triggers_sleep(self, monkeypatch, clock):
        _patch_time(monkeypatch, clock)
        limiter = rl.RateLimiter(max_per_minute=3)
        for _ in range(3):
            limiter.acquire()
        assert clock.sleeps == []
        # 第 4 次：窗口内已 3 个令牌，应触发限流 sleep
        limiter.acquire()
        assert len(clock.sleeps) == 1
        assert clock.sleeps[0] > 0  # 实际等待了正时长
        # acquire 内部的窗口过滤用的是入口时刻 now（sleep 之前），因此本次
        # 先休眠再 append，令牌为 3 个原有 + 1 个新 = 4（下一次 acquire 才会滚旧）
        assert len(limiter._tokens) == 4

    def test_new_window_recovers(self, monkeypatch, clock):
        _patch_time(monkeypatch, clock)
        limiter = rl.RateLimiter(max_per_minute=3)
        # 模拟旧令牌都在 900s 前（远早于 now=1000）
        limiter._tokens = [100.0, 100.0, 100.0]
        # 窗口（now-60=940）已过期，acquire 不应阻塞
        limiter.acquire()
        assert clock.sleeps == []
        # 仅保留本次新令牌
        assert len(limiter._tokens) == 1
        assert limiter._tokens[0] == pytest.approx(1000.0)

    def test_rolling_window_expires_old_tokens(self, monkeypatch, clock):
        _patch_time(monkeypatch, clock)
        limiter = rl.RateLimiter(max_per_minute=2)
        limiter.acquire()  # t=1000
        clock.now += 30
        limiter.acquire()  # t=1030
        # 此时两个令牌（1000, 1030）都在 60s 窗口内
        assert len(limiter._tokens) == 2
        # 推进到 1000+61=1061：第一个令牌 1000 过期，应只剩 1030
        clock.now = 1061
        limiter.acquire()  # 触发一次窗口裁剪
        # 1000 已滚出（1000 <= 1061-60=1001? 1000<=1001 True -> 被剔除）
        assert 1000.0 not in limiter._tokens
        assert 1030.0 in limiter._tokens
        assert len(limiter._tokens) == 2  # 1030 + 新 1061


class TestRateLimiterResetAndSingleton:
    def test_reset_clears_tokens(self, monkeypatch, clock):
        _patch_time(monkeypatch, clock)
        limiter = rl.RateLimiter(max_per_minute=5)
        limiter.acquire()
        limiter.acquire()
        assert len(limiter._tokens) == 2
        limiter.reset()
        assert limiter._tokens == []

    def test_get_global_limiter_singleton(self):
        a = rl.get_global_limiter()
        b = rl.get_global_limiter()
        assert a is b
        assert isinstance(a, rl.RateLimiter)
        assert a._max_per_minute == 20  # 模块默认配额


class TestRateLimiterConcurrency:
    def test_concurrent_count_within_quota(self):
        # 高配额、真实时钟、并发 acquire，验证计数准确且无越界
        limiter = rl.RateLimiter(max_per_minute=1000)
        n_threads = 200

        def worker():
            limiter.acquire()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 并发下锁保护，令牌数精确等于请求数且不超过配额
        assert len(limiter._tokens) == n_threads
        assert len(limiter._tokens) <= limiter._max_per_minute
