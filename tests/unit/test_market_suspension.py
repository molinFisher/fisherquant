"""G2 数据层直测：SuspensionService 内存停牌表 + akshare 尽力降级。

覆盖点：
- add_suspension / add_suspension_range（含端点）/ is_suspended 命中与未命中；
- load_from_akshare 的离线降级（akshare 不可用返回 0 且不抛）；
- load_from_akshare 的成功写入与解析容错；
- clear 清空。
"""
import sys

import pytest

from fisher.market.suspension import SuspensionService


def test_add_and_query_single():
    svc = SuspensionService()
    assert svc.is_suspended("600519.SH", "2024-01-02") is False
    svc.add_suspension("600519.SH", "2024-01-02")
    assert svc.is_suspended("600519.SH", "2024-01-02") is True
    # 其他标的 / 其他日期不受影响
    assert svc.is_suspended("600519.SH", "2024-01-03") is False
    assert svc.is_suspended("000001.SZ", "2024-01-02") is False


def test_add_range_inclusive_endpoints():
    svc = SuspensionService()
    svc.add_suspension_range("000001.SZ", "2024-02-01", "2024-02-03")
    for d in ("2024-02-01", "2024-02-02", "2024-02-03"):
        assert svc.is_suspended("000001.SZ", d) is True
    assert svc.is_suspended("000001.SZ", "2024-01-31") is False
    assert svc.is_suspended("000001.SZ", "2024-02-04") is False


def test_add_range_single_day():
    svc = SuspensionService()
    svc.add_suspension_range("A.SH", "2024-03-10", "2024-03-10")
    assert svc.is_suspended("A.SH", "2024-03-10") is True
    assert svc.is_suspended("A.SH", "2024-03-11") is False


def test_overlapping_ranges_merge():
    svc = SuspensionService()
    svc.add_suspension_range("X.SH", "2024-04-01", "2024-04-05")
    svc.add_suspension_range("X.SH", "2024-04-05", "2024-04-10")
    for d in (
        "2024-04-01",
        "2024-04-05",  # 端点重叠
        "2024-04-10",
    ):
        assert svc.is_suspended("X.SH", d) is True
    assert svc.is_suspended("X.SH", "2024-04-11") is False


def test_clear_empties_table():
    svc = SuspensionService()
    svc.add_suspension("A.SH", "2024-05-01")
    svc.clear()
    assert svc.is_suspended("A.SH", "2024-05-01") is False


# ---- load_from_akshare 降级 / 成功路径 ----


class _FakeRow(dict):
    pass


class _FakeDF:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        for i, r in enumerate(self._rows):
            yield i, r


class _FakeAkSuccess:
    def stock_suspend(self):
        return _FakeDF(
            [
                {"代码": "600519.SH", "停牌开始日期": "2024-06-01"},
                {"代码": "000001.SZ", "停牌开始日期": "2024-06-02"},
                {"symbol": "300750.SZ", "date": "2024-06-03"},
                {"代码": "", "停牌开始日期": "2024-06-04"},  # 空代码，应被跳过
            ]
        )


class _FakeAkFetchError:
    def stock_suspend(self):
        raise RuntimeError("network down")


def test_load_from_akshare_unavailable_returns_zero(monkeypatch):
    # 让 `import akshare` 抛 ImportError（离线安全降级）
    monkeypatch.setitem(sys.modules, "akshare", None)
    svc = SuspensionService()
    count = svc.load_from_akshare()
    assert count == 0  # 不抛异常即可


def test_load_from_akshare_fetch_error_returns_zero(monkeypatch):
    class _BadAk:
        def stock_suspend(self):
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "akshare", _BadAk())
    svc = SuspensionService()
    assert svc.load_from_akshare() == 0


def test_load_from_akshare_writes_records(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", _FakeAkSuccess())
    svc = SuspensionService()
    count = svc.load_from_akshare()
    # 4 行中 1 行空代码被跳过 -> 3 条
    assert count == 3
    assert svc.is_suspended("600519.SH", "2024-06-01") is True
    assert svc.is_suspended("000001.SZ", "2024-06-02") is True
    assert svc.is_suspended("300750.SZ", "2024-06-03") is True
    assert svc.is_suspended("UNKNOWN.SH", "2024-06-04") is False


def test_load_from_akshare_parse_failure_does_not_raise(monkeypatch):
    class _BadDF:
        def iterrows(self):
            raise ValueError("corrupt")

    class _BadAk:
        def stock_suspend(self):
            return _BadDF()

    monkeypatch.setitem(sys.modules, "akshare", _BadAk())
    svc = SuspensionService()
    # 解析异常被吞，返回已写入条数（此处为 0），不向外抛
    assert svc.load_from_akshare() == 0
