"""策略中心缓存联动（P0）的回测入口级测试：聚焦三条此前未断言的关键路径。

1. 数据就绪**阻断分支**：readiness.blocking=True 时 run_backtest 应提前返回
   "数据未就绪" 清单且**不构造回测引擎**（AC-1 / D1 不静默空跑）。
2. **adj_caliber 留痕**：成功路径下序列化元信息须携带每只标的的复权口径
   （A 股 qfq，非 A 股 none）——验证 P0-2 收益口径正确可追溯。
3. **清单渲染**：_render_readiness_manifest 把缺失项转成中文可读告警。

复用 test_backtest_callbacks 的 harness 思路（capture_dash_callbacks），但本文件
自带轻量 fixture，避免跨文件依赖；对 _readiness_report / _load_adjusted_bars /
BacktestEngine / BacktestSerializer 做定向 monkeypatch。
"""
import json
from types import SimpleNamespace

import polars as pl
import pytest

from fisher.dash_app.callbacks import backtest_callbacks as bc
from fisher.dash_app.services.strategy_data_service import (
    ReadinessReport, MissingItem,
)
from tests.helpers.dash_harness import capture_dash_callbacks


_STRATEGY = {"name": "bh", "type": "buy_and_hold", "params": {}}


class _SpyEngine:
    instances = []

    def __init__(self, **kw):
        _SpyEngine.instances.append(dict(kw))
        self.__dict__.update(kw)

    async def run(self, strategy):
        return {"nav_history": [1.0, 1.01, 1.02], "trades": []}


class _CapturingSerializer:
    """捕获 save() 的 metadata，便于断言 adj_caliber；cleanup/list_history 直接放行。"""
    last_metadata = None
    save_calls = 0

    def save(self, result_id, nav_history, trades=None, benchmark=None, metadata=None):
        _CapturingSerializer.last_metadata = metadata
        _CapturingSerializer.save_calls += 1
        return "fake"

    def cleanup(self, *a, **k):
        return None

    def list_history(self, *a, **k):
        return []


def _fake_bars(ticker="600519.SH"):
    return pl.DataFrame({
        "ticker": [ticker], "trade_date": ["2023-01-03"],
        "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
        "volume": [1000], "amount": [1e6], "market": ["a_share"],
    })


@pytest.fixture
def harness(monkeypatch):
    _SpyEngine.instances.clear()
    _CapturingSerializer.last_metadata = None
    _CapturingSerializer.save_calls = 0

    monkeypatch.setattr(bc, "ctx", SimpleNamespace(triggered=[]))
    monkeypatch.setattr(bc, "_run_async", lambda c: __import__("asyncio").run(c))
    monkeypatch.setattr(bc, "_get_cached_symbols", lambda *a, **k: [{"value": "600519.SH"}])
    monkeypatch.setattr(bc, "_load_bars", _fake_bars)
    monkeypatch.setattr(bc, "_default_risk_engine", lambda *a, **k: None)
    monkeypatch.setattr(bc, "BacktestEngine", _SpyEngine)
    monkeypatch.setattr(bc, "BacktestSerializer", _CapturingSerializer)
    yield


def _call_run(h, strategy_json, symbols, start, end, benchmark="none"):
    with capture_dash_callbacks() as app:
        bc.register_backtest_callbacks(app)
        run = app.get_callback("bt-progress-bar")
    return run(
        1, None, strategy_json, symbols,
        start, end, 1_000_000, 0.025, None, benchmark, False,
    )


class TestReadinessGateBlocking:
    def test_blocking_returns_manifest_and_skips_engine(self, harness, monkeypatch):
        blocking = ReadinessReport(
            ready=False, blocking=True,
            missing=[MissingItem(symbol="600519.SH", types=["daily", "adj"],
                                 out_of_range=False, note="未缓存（cache_catalog 无记录）")],
            symbols=["600519.SH"], requires_financials=False,
        )
        monkeypatch.setattr(bc, "_readiness_report",
                            lambda *a, **k: blocking)

        res = _call_run(harness, json.dumps(_STRATEGY), ["600519.SH"],
                        "2020-01-01", "2020-12-31")

        # 提前返回：状态文本 + 未构造引擎
        assert res[2] == "数据未就绪"
        assert _SpyEngine.instances == []
        # 清单区为 danger Alert + 含缺失标的
        summary = res[3]
        assert "数据未就绪" in str(summary)
        assert "600519.SH" in str(summary)


class TestAdjCaliberMetadata:
    def test_a_share_gets_qfq_caliber(self, harness, monkeypatch):
        ready = ReadinessReport(ready=True, blocking=False, missing=[],
                                symbols=["600519.SH"], requires_financials=False)
        monkeypatch.setattr(bc, "_readiness_report", lambda *a, **k: ready)
        # 复权注入路径：A 股走 _load_adjusted_bars -> qfq 归一（签名 symbol,start,end,adj_type）
        monkeypatch.setattr(bc, "_load_adjusted_bars",
                            lambda sym, *a, **k: _fake_bars(sym))

        res = _call_run(harness, json.dumps(_STRATEGY), ["600519.SH"],
                        "2020-01-01", "2020-12-31")
        assert res[2] == "回测完成"
        meta = _CapturingSerializer.last_metadata
        assert meta is not None
        assert meta["adj_caliber"] == {"600519.SH": "qfq"}

    def test_non_a_share_gets_none_caliber(self, harness, monkeypatch):
        ready = ReadinessReport(ready=True, blocking=False, missing=[],
                                symbols=["00700.HK"], requires_financials=False)
        monkeypatch.setattr(bc, "_readiness_report", lambda *a, **k: ready)
        monkeypatch.setattr(bc, "_load_adjusted_bars",
                            lambda sym, *a, **k: _fake_bars(sym))

        res = _call_run(harness, json.dumps(_STRATEGY), ["00700.HK"],
                        "2020-01-01", "2020-12-31")
        assert res[2] == "回测完成"
        meta = _CapturingSerializer.last_metadata
        assert meta["adj_caliber"] == {"00700.HK": "none"}


class TestPartialMissingStillRuns:
    def test_partial_missing_runs_and_warns(self, harness, monkeypatch):
        # 部分缺失（非全缺）-> 仍可跑，但结果区追加缺失提示（D1 不静默）
        partial = ReadinessReport(
            ready=False, blocking=False,
            missing=[MissingItem(symbol="600519.SH", types=["financials"],
                                 out_of_range=False, note="")],
            symbols=["600519.SH"], requires_financials=True,
        )
        monkeypatch.setattr(bc, "_readiness_report", lambda *a, **k: partial)
        monkeypatch.setattr(bc, "_load_adjusted_bars",
                            lambda sym, *a, **k: _fake_bars(sym))
        res = _call_run(harness, json.dumps(_STRATEGY), ["600519.SH"],
                        "2020-01-01", "2020-12-31")
        assert res[2] == "回测完成"          # 未阻断
        assert _SpyEngine.instances != []     # 实际跑了引擎
        # 结果区含部分缺失提示（PRD：部分缺仍可跑但显式告知被跳过标的）
        assert "被跳过" in str(res[3]) and "600519.SH" in str(res[3])


class TestAdjTypeFor:
    def test_a_share_is_qfq(self):
        assert bc._adj_type_for("600519.SH") == "qfq"
        assert bc._adj_type_for("000001.SZ") == "qfq"
        assert bc._adj_type_for("830799.BJ") == "qfq"

    def test_non_a_share_is_none(self):
        assert bc._adj_type_for("00700.HK") is None
        assert bc._adj_type_for("AAPL") is None
        assert bc._adj_type_for("") is None


class TestRenderReadinessManifest:
    def test_renders_symbols_and_types(self):
        report = ReadinessReport(
            ready=False, blocking=True,
            missing=[
                MissingItem(symbol="600519.SH", types=["daily", "adj"],
                           out_of_range=False, note="未缓存（cache_catalog 无记录）"),
                MissingItem(symbol="000001.SZ", types=["financials"],
                           out_of_range=True, note=""),
            ],
            symbols=["600519.SH", "000001.SZ"], requires_financials=True,
        )
        div = bc._render_readiness_manifest(report)
        text = str(div)
        # 标的
        assert "600519.SH" in text and "000001.SZ" in text
        # 中文类型名映射
        assert "日线" in text and "复权因子" in text and "财务数据" in text
        # 越界提示
        assert "区间越界" in text
        # 阻断告警
        assert "已阻断回测" in text

    def test_empty_missing_yields_generic_note(self):
        report = ReadinessReport(ready=False, blocking=True, missing=[],
                                symbols=[], requires_financials=False)
        div = bc._render_readiness_manifest(report)
        assert "数据未就绪" in str(div)
