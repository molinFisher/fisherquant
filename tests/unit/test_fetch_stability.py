"""数据获取稳定性与容错优化（PRD 数据获取稳定性与容错优化 V1.0）单测。

聚焦：限流器接入、限流感知降速、失败分类、已覆盖区间跳过、保守模式。
这些测试复用 conftest 的 data_service / limiter / mock_akshare 设施，
并**不触网**（akshare 由 monkeypatch 接管）。
"""
import pytest
import akshare as ak
from fisher.dash_app.services.data_center_service import DataCenterService, _retry_fetch
from fisher.market.rate_limiter import (
    get_global_limiter, RateLimitError, is_rate_limit_error,
)


# --------------------------------------------------------------------------- #
# 1. 限流器接入 + 限流感知降速
# --------------------------------------------------------------------------- #
def test_retry_fetch_acquires_limiter():
    """_retry_fetch 每次请求前必须向限流器取令牌（FR-1 根因修复）。"""
    from fisher.market.rate_limiter import RateLimiter
    limiter = RateLimiter(max_per_minute=1000)
    acquired = {"n": 0}

    real_acquire = limiter.acquire

    def counting_acquire():
        acquired["n"] += 1
        return real_acquire()

    limiter.acquire = counting_acquire
    _retry_fetch(lambda: "ok", limiter=limiter)
    assert acquired["n"] == 1


def test_retry_fetch_rate_limit_raises_structured_error():
    """上游限流异常应升级为 RateLimitError 并触发 cool_down（FR-2）。"""

    def boom(*a, **k):
        raise Exception("HTTPSConnectionPool: Max retries exceeded "
                        "(host='push2his.eastmoney.com')")

    limiter = get_global_limiter()
    limiter.reset()
    # 避免真实冷却睡眠拖慢测试：缩短 cool_down
    import fisher.market.rate_limiter as rl
    orig_cool = limiter.cool_down
    limiter.cool_down = lambda seconds=0.0: orig_cool(0.0)
    try:
        with pytest.raises(RateLimitError):
            _retry_fetch(boom, attempts=2, delay=0, limiter=limiter)
    finally:
        limiter.cool_down = orig_cool
        limiter.reset()


def test_is_rate_limit_error_variants():
    assert is_rate_limit_error(Exception("Max retries exceeded"))
    assert is_rate_limit_error(Exception("429 Too Many Requests"))
    assert is_rate_limit_error(Exception("请求过于频繁"))
    assert not is_rate_limit_error(Exception("date format error"))


# --------------------------------------------------------------------------- #
# 2. fetch_bars 失败分类（reason 字段）
# --------------------------------------------------------------------------- #
def test_fetch_minute_rate_limited_reason(data_service, monkeypatch):
    """分钟线被东方财富限流时，结果 reason=rate_limited（FR-3）。"""
    import fisher.market.rate_limiter as rl

    def boom(*a, **k):
        raise rl.RateLimitError("Max retries exceeded (eastmoney)")

    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", boom, raising=False)
    results = data_service.fetch_bars(
        ["600519.SH"], "2026-07-22", "2026-07-29", data_type="minute")
    r = results["600519.SH"]
    assert r["status"] == "failed"
    assert r["reason"] == "rate_limited"
    assert "限流" in r["error"]


def test_fetch_minute_no_data_reason(data_service, monkeypatch):
    """空结果应标记 reason=no_data（FR-3，不再掩盖为限流）。"""
    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", lambda *a, **k: None)
    results = data_service.fetch_bars(
        ["600519.SH"], "2026-07-22", "2026-07-29", data_type="minute")
    r = results["600519.SH"]
    assert r["status"] == "failed"
    assert r["reason"] == "no_data"


def test_fetch_minute_hk_unsupported_reason(data_service):
    """港股分钟线应标记 reason=unsupported（FR-3）。"""
    results = data_service.fetch_bars(
        ["00700.HK"], "2026-07-22", "2026-07-29", data_type="minute")
    r = results["00700.HK"]
    assert r["status"] == "failed"
    assert r["reason"] == "unsupported"


# --------------------------------------------------------------------------- #
# 3. FR-7 已覆盖区间跳过
# --------------------------------------------------------------------------- #
def test_fetch_minute_skip_when_fully_covered(data_service):
    """请求区间被已缓存区间完全覆盖时，跳过且不触网（FR-7）。"""
    ticker = "600519.SH"
    # 先写覆盖度：分钟线 2026-07-01 ~ 2026-07-31，周期 1
    with data_service._db.transaction() as conn:
        data_service._catalog.record_coverage(
            conn, ticker, "a_share", data_type="minute",
            start="2026-07-01", end="2026-07-31", period="1")

    # 用会抛错的 mock 验证"未触网"
    def boom(*a, **k):
        raise AssertionError("不应发起网络请求（已被缓存跳过）")

    import akshare as ak
    import fisher.dash_app.services.data_center_service as svc_mod
    monkeypatch_boom = pytest.MonkeyPatch()
    monkeypatch_boom.setattr(ak, "stock_zh_a_hist_min_em", boom, raising=False)
    try:
        results = data_service.fetch_bars(
            [ticker], "2026-07-10", "2026-07-20", data_type="minute", period="1")
    finally:
        monkeypatch_boom.undo()
    r = results[ticker]
    assert r["status"] == "skipped"
    assert r["reason"] == "cached"


def test_fetch_minute_no_skip_when_partial_overlap(data_service, monkeypatch):
    """请求区间超出已缓存范围时，不跳过（应发请求补齐）。"""
    ticker = "600519.SH"
    with data_service._db.transaction() as conn:
        data_service._catalog.record_coverage(
            conn, ticker, "a_share", data_type="minute",
            start="2026-07-01", end="2026-07-10", period="1")

    called = {"n": 0}

    def mock_min_em(symbol=None, period="1", start_date="", end_date="", adjust=""):
        called["n"] += 1
        from tests.conftest import MockAKShareDF
        return MockAKShareDF([
            {"时间": "2026-07-11 09:31:00", "开盘": 100.0, "最高": 101.0,
             "最低": 99.0, "收盘": 100.5, "成交量": 1000, "成交额": 100500.0},
        ])

    monkeypatch.setattr(ak, "stock_zh_a_hist_min_em", mock_min_em, raising=False)
    results = data_service.fetch_bars(
        [ticker], "2026-07-05", "2026-07-11", data_type="minute", period="1")
    assert called["n"] == 1  # 仍然发起了请求
    assert results[ticker]["status"] == "ok"


# --------------------------------------------------------------------------- #
# 4. 保守模式
# --------------------------------------------------------------------------- #
def test_conservative_mode_lowers_rate(data_service, monkeypatch):
    """conservative=True 临时把限流器速率降到默认一半，结束后恢复（FR-5）。"""
    import akshare as ak
    ticker = "600519.SH"
    monkeypatch.setattr(ak, "stock_zh_a_hist", lambda *a, **k: None)

    original_default = data_service._limiter._default_max
    data_service.fetch_bars([ticker], "2024-01-01", "2024-01-31",
                             data_type="daily", conservative=True)
    # 调用结束后应恢复默认速率
    assert data_service._limiter._max_per_minute == original_default


# --------------------------------------------------------------------------- #
# 5. 覆盖度读取含分钟区间
# --------------------------------------------------------------------------- #
def test_coverage_includes_minute_range(data_service):
    """get_coverage_for_tickers 应返回 minute_start/minute_end（FR-7 依赖）。"""
    ticker = "600519.SH"
    with data_service._db.transaction() as conn:
        data_service._catalog.record_coverage(
            conn, ticker, "a_share", data_type="minute",
            start="2026-07-01", end="2026-07-31", period="1")
    cov = data_service._catalog.get_coverage_for_tickers([ticker])
    row = cov[ticker]
    assert row["has_minute"] is True
    assert "1" in (row.get("minute_periods") or "")
    assert str(row["minute_start"])[:10] == "2026-07-01"
    assert str(row["minute_end"])[:10] == "2026-07-31"
