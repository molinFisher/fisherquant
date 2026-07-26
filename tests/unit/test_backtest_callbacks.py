"""Phase 3 焦点：backtest_callbacks 单元级测试（不依赖 HTTP / 真实 app）。

通过 tests/helpers/dash_harness 捕获 @app.callback 闭包，直接调用其内部函数并断言关键
输出，重点验证：
  - `_collect_bar_rows` 正确补全 trade_date / bar_time（P0-4 T+1 结算依赖）
  - 主回测路径确实传入 slippage_bps=5（P0-3）、risk_engine（P0-5）、seed=42（P2-14）
  - 6 处 `bars_pl` 构造（pl.DataFrame(_collect_bar_rows(...))）列一致
"""
import json
import math
from datetime import datetime
from types import SimpleNamespace

import polars as pl
import pytest

from fisher.dash_app.callbacks import backtest_callbacks as bc
from tests.helpers.dash_harness import capture_dash_callbacks, FakeDashApp


# --------------------------------------------------------------------------- #
# helper 函数单测
# --------------------------------------------------------------------------- #
class TestCollectBarRows:
    def _df(self, trade_date="2023-01-03", with_market=True):
        cols = {
            "ticker": ["000001.SZ"],
            "trade_date": [trade_date],
            "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
            "volume": [1000], "amount": [1e6],
        }
        if with_market:
            cols["market"] = ["a_share"]
        return pl.DataFrame(cols)

    def test_adds_trade_date_and_bar_time(self):
        rows = bc._collect_bar_rows(self._df())
        assert len(rows) == 1
        r = rows[0]
        assert r["trade_date"] == "2023-01-03"
        expected_ts = datetime.strptime("2023-01-03", "%Y-%m-%d").timestamp()
        assert r["bar_time"] == pytest.approx(expected_ts, abs=1.0)
        assert r["open"] == 10.0 and r["close"] == 10.2
        assert r["market"] == "a_share"

    def test_strips_time_component_from_date(self):
        rows = bc._collect_bar_rows(self._df(trade_date="2023-01-03 00:00:00"))
        assert rows[0]["trade_date"] == "2023-01-03"

    def test_invalid_date_yields_zero_bar_time(self):
        rows = bc._collect_bar_rows(self._df(trade_date="not-a-date"))
        assert rows[0]["bar_time"] == 0.0

    def test_missing_market_column_defaults_to_a_share(self):
        rows = bc._collect_bar_rows(self._df(with_market=False))
        assert rows[0]["market"] == "a_share"

    def test_multiple_rows_preserve_order(self):
        df = pl.DataFrame({
            "ticker": ["000001.SZ", "600519.SH"],
            "trade_date": ["2023-01-03", "2023-01-04"],
            "open": [10.0, 100.0], "high": [10.5, 101.0], "low": [9.8, 99.0],
            "close": [10.2, 100.5], "volume": [1000, 500], "amount": [1e6, 5e6],
            "market": ["a_share", "a_share"],
        })
        rows = bc._collect_bar_rows(df)
        assert [r["ticker"] for r in rows] == ["000001.SZ", "600519.SH"]


class TestComputeBenchmarkNav:
    def test_none_closes(self):
        assert bc._compute_benchmark_nav(None, 10) is None

    def test_too_short_closes(self):
        assert bc._compute_benchmark_nav([1.0], 10) is None

    def test_multiplicative_nav(self):
        nav = bc._compute_benchmark_nav([1.0, 1.1, 1.2], 3)
        assert nav[0] == pytest.approx(1.0)
        # 1.0 * (1.1/1.0) * (1.2/1.1) = 1.2
        assert nav[-1] == pytest.approx(1.2, rel=1e-6)

    def test_pads_to_nav_len(self):
        nav = bc._compute_benchmark_nav([1.0, 1.1, 1.2], 5)
        assert len(nav) == 5
        assert nav[3] == nav[4] == pytest.approx(nav[2], rel=1e-9)


class TestDetectRegimes:
    def test_short_series_all_neutral(self):
        closes = [1.0, 1.01, 0.99] * 5
        regimes = bc._detect_regimes(closes)
        assert regimes == ["neutral"] * len(closes)

    def test_long_uptrend_has_bull(self):
        closes = [float(100 + i) for i in range(80)]  # 单调上涨
        regimes = bc._detect_regimes(closes)
        assert len(regimes) == len(closes)
        assert all(r in ("neutral", "bull", "bear", "sideways") for r in regimes)
        assert "bull" in regimes


class TestRegimeStats:
    def test_returns_three_environments(self):
        nav = [1.0 + i * 0.001 for i in range(80)]
        stats = bc._compute_regime_stats(nav, ["neutral"] * len(nav))
        for key in ("bull", "bear", "sideways"):
            assert key in stats
            assert "return" in stats[key] and "sharpe" in stats[key]
            assert stats[key]["days"] == 0
            assert stats[key]["return"] == 0.0

    def test_bull_window_has_positive_return(self):
        nav = [1.0] * 40
        # 后 40 根上涨 -> 标记为 bull
        nav += [1.0 + i * 0.01 for i in range(40)]
        regimes = ["neutral"] * 40 + ["bull"] * 40
        stats = bc._compute_regime_stats(nav, regimes)
        assert stats["bull"]["days"] == 40
        assert stats["bull"]["return"] > 0


class TestRegimeTable:
    def test_four_rows(self):
        stats = {
            "bull": {"return": 0.1, "sharpe": 1.0, "days": 10},
            "bear": {"return": -0.05, "sharpe": -0.5, "days": 5},
            "sideways": {"return": 0.0, "sharpe": 0.0, "days": 3},
        }
        table = bc._build_regime_table(stats)
        # html.Table 的 children 为 [header Tr, bull Tr, bear Tr, sideways Tr]
        assert len(table.children) == 4


class TestDefaultRiskEngine:
    def test_returns_none_when_config_unavailable(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no config")
        monkeypatch.setattr(bc, "load_risk_config", boom)
        assert bc._default_risk_engine() is None

    def test_builds_engine_from_real_config(self, monkeypatch):
        # 用确定性的 4 条规则配置，验证 build_risk_engine 真正接入（P0-5）
        cfg = {
            "pre_trade": [
                {"rule": "MaxPosition", "params": {"max_pct": 0.2}},
                {"rule": "DailyLossLimit", "params": {"max_loss_pct": 0.05}},
                {"rule": "PriceLimit"},
                {"rule": "SectorLimit", "params": {"max_pct": 0.3}},
            ]
        }
        monkeypatch.setattr(bc, "load_risk_config", lambda *a, **k: cfg)
        engine = bc._default_risk_engine()
        assert engine is not None
        assert len(engine._rules) == 4


class TestLoadStrategies:
    def test_only_enabled_valid_returned(self, tmp_path, monkeypatch):
        enabled = {"name": "s1", "type": "buy_hold", "enabled": True}
        disabled = {"name": "s2", "type": "buy_hold", "enabled": False}
        broken = "{not json"
        (tmp_path / "a.json").write_text(json.dumps(enabled), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(disabled), encoding="utf-8")
        (tmp_path / "c.json").write_text(broken, encoding="utf-8")
        monkeypatch.setattr(bc, "STRATEGIES_DIR", tmp_path)
        result = bc._load_strategies()
        assert [s["name"] for s in result] == ["s1"]


# --------------------------------------------------------------------------- #
# 主回测路径：捕获闭包并验证 slippage_bps / risk_engine / seed 传入
# --------------------------------------------------------------------------- #
_STRATEGY = {"name": "bh", "type": "buy_and_hold", "params": {}}
_RISK_SENTINEL = object()


class _SpyPaper:
    instances = []

    def __init__(self, **kw):
        _SpyPaper.instances.append(dict(kw))
        self.__dict__.update(kw)


class _SpyEngine:
    instances = []

    def __init__(self, **kw):
        _SpyEngine.instances.append(dict(kw))
        self.__dict__.update(kw)

    async def run(self, strategy):
        return {"nav_history": [1.0, 1.01, 1.02], "trades": []}


class _PlSpy:
    """记录所有 pl.DataFrame(list_of_dicts) 调用的列名，用于一致性断言。"""
    calls = []
    _real = pl.DataFrame  # 捕获原始构造器，避免递归

    def __call__(self, data=None, *a, **k):
        if isinstance(data, list) and data and isinstance(data[0], dict):
            _PlSpy.calls.append(list(data[0].keys()))
        return _PlSpy._real(data, *a, **k)


@pytest.fixture
def spied_backtest(monkeypatch):
    _SpyPaper.instances.clear()
    _SpyEngine.instances.clear()
    _PlSpy.calls.clear()

    # 用假数据替代数据库读取
    def fake_load_bars(*a, **k):
        return pl.DataFrame({
            "ticker": ["000001.SZ"], "trade_date": ["2023-01-03"],
            "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
            "volume": [1000], "amount": [1e6], "market": ["a_share"],
        })

    def fake_symbols(*a, **k):
        return [{"label": "000001.SZ", "value": "000001.SZ"}]

    class _FakeSerializer:
        def save(self, *a, **k):
            return "fake"
        def cleanup(self, *a, **k):
            return None
        def list_history(self, *a, **k):
            return []

    # 直接调用闭包时 dash.callback_context 不可用，mock 为无触发
    monkeypatch.setattr(bc, "ctx", SimpleNamespace(triggered=[]))

    # 隔离事件循环，避免 pytest-asyncio 环境下的 loop 复用问题
    def _run_async(coro):
        import asyncio
        return asyncio.run(coro)

    monkeypatch.setattr(bc, "_run_async", _run_async)

    monkeypatch.setattr(bc, "_load_bars", fake_load_bars)
    monkeypatch.setattr(bc, "_get_cached_symbols", fake_symbols)
    monkeypatch.setattr(bc, "_default_risk_engine", lambda *a, **k: _RISK_SENTINEL)
    monkeypatch.setattr(bc, "BacktestSerializer", _FakeSerializer)
    monkeypatch.setattr(bc, "PaperEngine", _SpyPaper)
    monkeypatch.setattr(bc, "BacktestEngine", _SpyEngine)
    monkeypatch.setattr(bc.pl, "DataFrame", _PlSpy())
    yield


class TestMainBacktestPath:
    def test_run_backtest_passes_correct_engine_params(self, spied_backtest):
        with capture_dash_callbacks() as app:
            bc.register_backtest_callbacks(app)
            run = app.get_callback("bt-progress-bar")

        result = run(
            1, None, json.dumps(_STRATEGY), ["000001.SZ"],
            "2020-01-01", "2020-12-31", 1_000_000, 0.025, None, "none", False,
        )
        # 成功路径返回 11 元组，第 3 项是进度文本
        assert result[2] == "回测完成"
        # P0-3：滑点万分之五
        assert _SpyPaper.instances[-1]["slippage_bps"] == bc.DEFAULT_SLIPPAGE_BPS == 5.0
        # P0-5 + P2-14：风险引擎与种子传入
        eng_kw = _SpyEngine.instances[-1]
        assert eng_kw["risk_engine"] is _RISK_SENTINEL
        assert eng_kw["seed"] == 42

    def test_cancel_path_returns_early(self, spied_backtest, monkeypatch):
        # 模拟由“取消”按钮触发
        monkeypatch.setattr(bc, "ctx", SimpleNamespace(
            triggered=[{"prop_id": "bt-cancel-btn.n_clicks"}]))
        with capture_dash_callbacks() as app:
            bc.register_backtest_callbacks(app)
            run = app.get_callback("bt-progress-bar")
        result = run(
            None, 1, json.dumps(_STRATEGY), ["000001.SZ"],
            "2020-01-01", "2020-12-31", 1_000_000, 0.025, None, "none", False,
        )
        assert result[2] == "回测已取消"
        assert _SpyEngine.instances == []  # 取消时不应构造引擎

    def test_missing_strategy_aborts(self, spied_backtest):
        with capture_dash_callbacks() as app:
            bc.register_backtest_callbacks(app)
            run = app.get_callback("bt-progress-bar")
        result = run(1, None, None, ["000001.SZ"], "2020-01-01", "2020-12-31",
                       1_000_000, 0.025, None, "none", False)
        assert result[2] == "请先选择策略"


class TestAllBarsPlConstructionsConsistent:
    """验证 6 处 bars_pl 构造（pl.DataFrame(_collect_bar_rows(...))）列一致。"""
    def test_six_paths_produce_identical_columns(self, spied_backtest):
        strat2 = {"name": "bh2", "type": "buy_and_hold", "params": {}}
        with capture_dash_callbacks() as app:
            bc.register_backtest_callbacks(app)
            run = app.get_callback("bt-progress-bar")
            multi = app.get_callback("bt-multi-results")
            wf = app.get_callback("bt-wf-results")
            sens = app.get_callback("bt-sens-results")
            regime = app.get_callback("bt-regime-results")

            run(1, None, json.dumps(_STRATEGY), ["000001.SZ"],
                "2020-01-01", "2020-12-31", 1_000_000, 0.025, None, "none", False)
            multi(1, [json.dumps(_STRATEGY), json.dumps(strat2)], ["000001.SZ"],
                  "2020-01-01", "2020-12-31", 1_000_000, 0.025)
            wf(1, json.dumps(_STRATEGY), 8, "2020-01-01", "2020-12-31")
            sens(1, json.dumps(_STRATEGY), "fast", 1, 10, 5, "", None, None, None,
                 "2020-01-01", "2020-12-31")
            regime(1, json.dumps(_STRATEGY), ["000001.SZ"],
                   "2020-01-01", "2020-12-31", "none")

        # 至少 5 个路径被触发（sensitivity 单次回测 1 次，run 1 次，multi 1 次，
        # wf 1 次，regime 1 次），全部列名一致
        assert len(_PlSpy.calls) >= 5
        expected_cols = ["ticker", "trade_date", "bar_time", "open", "high",
                         "low", "close", "volume", "amount", "market"]
        for cols in _PlSpy.calls:
            assert cols == expected_cols
