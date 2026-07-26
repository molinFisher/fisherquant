"""Phase 3 单元级测试：factor/viz/report/settings/home 5 个 Dash 回调模块。

不启动真实 Dash server、不触网、不写真实数据库/磁盘：
  - 通过 tests/helpers/dash_harness 的 capture_dash_callbacks 捕获 @app.callback 闭包；
  - 用 monkeypatch 注入假 DB / 假 Serializer / 假服务，并隔离事件循环（这些模块无 async）；
  - 对模块级纯函数（update_symbol_count / update_factor_count / load_kline_symbols /
    toggle_mixed_config / _generate_report / _build_recent_backtests）直接单测；
  - 每个模块都包含结构性断言（register_X_callbacks 成功 + 关键回调可 get_callback 取回）
    与代表性回调闭包调用断言（校验关键文本 / 组件类型 / 数值）。
"""
import inspect
import pathlib
from types import SimpleNamespace

import dash
from dash import html, dcc, dash_table, no_update
import dash_bootstrap_components as dbc
import polars as pl

from tests.helpers.dash_harness import capture_dash_callbacks

from fisher.dash_app.callbacks import factor_callbacks as fc
from fisher.dash_app.callbacks import viz_callbacks as vc
from fisher.dash_app.callbacks import report_callbacks as rc
from fisher.dash_app.callbacks import settings_callbacks as sc
from fisher.dash_app.callbacks import home_callbacks as hc


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _cb_by_arity(app, nargs):
    """当同一输出 id 有多个回调（如 settings-save-status 的 allow_duplicate），
    用参数个数唯一确定一个闭包。"""
    for fn in app.all_callbacks():
        if len(inspect.signature(fn).parameters) == nargs:
            return fn
    raise KeyError(f"no callback with {nargs} args")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def iter_rows(self):
        for r in self._rows:
            yield r


class _FakeDuck:
    def __init__(self, rows):
        self._rows = rows

    def query_df(self, sql, params=None):
        return _Rows(self._rows)


# --------------------------------------------------------------------------- #
# factor_callbacks
# --------------------------------------------------------------------------- #
class TestFactorCallbacks:
    def test_register_and_key_callback(self):
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-progress")
        assert callable(cb)
        assert app.callback_count() >= 5

    def test_update_symbol_count(self):
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-symbol-count")
        assert cb([]) == "未选择标的"
        assert cb(["000001.SZ", "600519.SH"]) == "已选择 2 个标的"

    def test_update_factor_count(self):
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-factor-count")
        assert cb([]) == "未选择因子"
        assert cb(["mom", "rsi"]) == "已选择 2 个因子"

    def test_load_cached_symbols(self, monkeypatch):
        db = _FakeDuck(rows=[[("000001.SZ",)], [("600519.SH",)]])
        # query_df 返回 polars df 以匹配 iter_rows
        class _PolarsDB:
            def query_df(self, sql, params=None):
                return pl.DataFrame({"ticker": ["000001.SZ", "600519.SH"]})
        monkeypatch.setattr(fc, "_get_db", lambda: _PolarsDB())
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-symbols")
        sym_opts, prev_opts = cb("tab-compute")
        assert sym_opts == [
            {"label": "000001.SZ", "value": "000001.SZ"},
            {"label": "600519.SH", "value": "600519.SH"},
        ]
        assert prev_opts == sym_opts

    def test_load_cached_symbols_db_error_returns_empty(self, monkeypatch):
        class _BoomDB:
            def query_df(self, sql, params=None):
                raise RuntimeError("db down")
        monkeypatch.setattr(fc, "_get_db", lambda: _BoomDB())
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-symbols")
        sym_opts, prev_opts = cb("tab-compute")
        assert sym_opts == [] and prev_opts == []

    def test_compute_factors_success(self, monkeypatch):
        class _FakeFactor:
            def __init__(self, name):
                self.name = name

            def compute(self, df):
                return df.with_columns((pl.col("close") * 1.0).alias(self.name))

        class _FakeRegistry:
            @staticmethod
            def get(fname):
                return _FakeFactor(fname)

        class _PolarsDB:
            def query_df(self, sql, params=None):
                return pl.DataFrame({
                    "trade_date": ["2023-01-03", "2023-01-04"],
                    "open": [10.0, 10.1], "high": [10.5, 10.6],
                    "low": [9.8, 9.9], "close": [10.2, 10.3],
                    "volume": [1000, 1100],
                })

        saved = []
        monkeypatch.setattr(fc, "_get_db", lambda: _PolarsDB())
        monkeypatch.setattr(fc, "FactorRegistry", _FakeRegistry)
        monkeypatch.setattr(fc, "FactorStorage",
                            SimpleNamespace(save=lambda s, df: saved.append((s, df))))

        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-progress")
        progress, label, status_el = cb(1, ["000001.SZ"], ["f1"])
        assert progress == 100
        assert label == "100%"
        assert isinstance(status_el, html.Div)
        # 校验状态文本含成功行与因子列数
        text = " ".join(str(c.children) for c in status_el.children)
        assert "✓ 000001.SZ/f1: 1 列" in text
        assert saved == [("000001.SZ", saved[0][1])]

    def test_compute_factors_no_symbols(self, monkeypatch):
        monkeypatch.setattr(fc, "_get_db", lambda: _FakeDuck(rows=[]))
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-compute-progress")
        progress, label, status_el = cb(1, [], ["f1"])
        assert progress == 0 and label == "0%"
        assert "请先选择标的" in str(status_el.children)

    def test_preview_factor_data_success(self, monkeypatch):
        class _PolarsDB:
            def query_df(self, sql, params=None):
                return pl.DataFrame({
                    "trade_date": ["2023-01-03", "2023-01-04"],
                    "open": [10.0, 10.1], "high": [10.5, 10.6],
                    "low": [9.8, 9.9], "close": [10.2, 10.3],
                    "volume": [1000, 1100],
                })

        monkeypatch.setattr(fc, "_get_db", lambda: _PolarsDB())
        monkeypatch.setattr(
            fc, "FactorStorage",
            SimpleNamespace(load_with_factors=lambda s, df: df.with_columns(
                (pl.col("close") * 1.0).alias("f1"))))

        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-preview-table-container")
        table, stats = cb("000001.SZ")
        assert isinstance(table, dash_table.DataTable)
        assert any(c["id"] == "f1" for c in table.columns)
        assert "因子列" in str(stats.children)

    def test_preview_factor_data_none_symbol(self, monkeypatch):
        monkeypatch.setattr(fc, "_get_db", lambda: _FakeDuck(rows=[]))
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-preview-table-container")
        table, stats = cb(None)
        assert "请选择标的" in str(table.children)
        assert stats == "请选择标的"

    def test_preview_factor_data_query_failure(self, monkeypatch):
        class _BoomDB:
            def query_df(self, sql, params=None):
                raise RuntimeError("boom")
        monkeypatch.setattr(fc, "_get_db", lambda: _BoomDB())
        with capture_dash_callbacks() as app:
            fc.register_factor_callbacks(app)
            cb = app.get_callback("factor-preview-table-container")
        table, stats = cb("000001.SZ")
        assert "数据查询失败" in str(table.children)
        assert stats == "数据加载失败"


# --------------------------------------------------------------------------- #
# viz_callbacks
# --------------------------------------------------------------------------- #
class _FakeSerializer:
    def __init__(self, payload):
        self._payload = payload

    def load(self, backtest_id):
        if self._payload is _SENTINEL_RAISE:
            raise RuntimeError("serializer failure")
        return self._payload


_SENTINEL_RAISE = object()


class TestVizCallbacks:
    def test_register_and_key_callback(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-equity-chart")
        assert callable(cb)
        assert app.callback_count() >= 8

    def test_load_backtest_from_url_empty(self, monkeypatch):
        monkeypatch.setattr(vc, "BacktestSerializer", lambda: _FakeSerializer(None))
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-backtest-id")
        bid, data, loading, style = cb("")
        assert bid is None and data is None
        assert style == {"display": "none"}
        assert isinstance(loading, str) and "回测ID" in loading

    def test_load_backtest_from_url_load_failure(self, monkeypatch):
        monkeypatch.setattr(vc, "BacktestSerializer",
                            lambda: _FakeSerializer(_SENTINEL_RAISE))
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-backtest-id")
        bid, data, loading, style = cb("?backtest_id=btX")
        assert bid is None and data is None
        assert "失败" in loading and style == {"display": "none"}

    def test_load_backtest_from_url_success(self, monkeypatch):
        payload = {
            "equity": [1.0, 1.1, 1.2],
            "benchmark": [1.0, 1.05, 1.1],
            "trades": [{"ticker": "000001.SZ", "side": "buy", "quantity": 100,
                        "price": 10.0, "commission": 0.1}],
            "metadata": {"strategy": "S"},
        }
        monkeypatch.setattr(vc, "BacktestSerializer", lambda: _FakeSerializer(payload))
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-backtest-id")
        bid, data, loading, style = cb("?backtest_id=bt1")
        assert bid == "bt1"
        assert data["equity"] == [1.0, 1.1, 1.2]
        assert data["metadata"]["strategy"] == "S"
        assert isinstance(loading, html.Div)
        assert style == {"display": "block"}

    def test_render_equity(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-equity-chart")
        # 错误 tab -> no_update
        assert cb("tab-drawdown", {"equity": [1, 2]}) is no_update
        # 无净值 -> 提示
        res = cb("tab-equity", {"equity": []})
        assert isinstance(res, html.Div) and "无净值数据" in str(res.children)
        # 正常 -> dcc.Graph
        res = cb("tab-equity", {"equity": [1.0, 1.1], "benchmark": []})
        assert isinstance(res, dcc.Graph)

    def test_render_drawdown(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-drawdown-chart")
        assert cb("tab-equity", {"equity": [1, 2]}) is no_update
        res = cb("tab-drawdown", {"equity": [1.0, 1.1, 0.9]})
        assert isinstance(res, dcc.Graph)

    def test_render_heatmap(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-monthly-heatmap")
        res = cb("tab-heatmap", {"equity": [1.0 + i * 0.01 for i in range(50)]})
        assert isinstance(res, dcc.Graph)

    def test_render_histogram(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-return-histogram")
        res = cb("tab-histogram", {"equity": [1.0 + i * 0.01 for i in range(50)]})
        assert isinstance(res, dcc.Graph)

    def test_render_trades(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-trade-log")
        res = cb("tab-trades", {"trades": []})
        assert isinstance(res, html.Div) and "无交易记录" in str(res.children)
        trades = [{"ticker": "000001.SZ", "side": "buy", "quantity": 100,
                   "price": 10.0, "commission": 0.1, "timestamp": "2024-01-02"}]
        res = cb("tab-trades", {"trades": trades})
        assert isinstance(res, dash_table.DataTable)

    def test_load_kline_symbols(self):
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-kline-symbol")
        assert cb(None) == []
        opts = cb({"metadata": {"symbols": ["000001.SZ", "600519.SH"]}})
        assert opts == [
            {"label": "000001.SZ", "value": "000001.SZ"},
            {"label": "600519.SH", "value": "600519.SH"},
        ]

    def test_render_kline(self, monkeypatch):
        class _KlineDB:
            _initialized = False

            def query_df(self, sql, params=None):
                return pl.DataFrame({
                    "ticker": ["000001.SZ"], "trade_date": ["2023-01-03"],
                    "open": [10.0], "high": [10.5], "low": [9.8],
                    "close": [10.2], "volume": [1000], "amount": [1e6],
                    "market": ["a_share"],
                })
        monkeypatch.setattr(vc, "DuckDBManager", _KlineDB)
        with capture_dash_callbacks() as app:
            vc.register_viz_callbacks(app)
            cb = app.get_callback("viz-kline-chart")
        # 错误 tab
        assert cb("tab-equity", "000001.SZ", {"metadata": {}}) is no_update
        # 未选标的
        res = cb("tab-kline", None, {"metadata": {}, "equity": [1]})
        assert isinstance(res, html.Div) and "请先选择标的" in str(res.children)
        # 正常
        data = {"metadata": {"start_date": "2023-01-01", "end_date": "2023-12-31"},
                "equity": [1], "trades": []}
        res = cb("tab-kline", "000001.SZ", data)
        assert isinstance(res, dcc.Graph)


# --------------------------------------------------------------------------- #
# report_callbacks
# --------------------------------------------------------------------------- #
class TestReportCallbacks:
    def test_register_and_key_callback(self):
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-download")
        assert callable(cb)
        assert app.callback_count() >= 2

    def test_generate_report_none(self, monkeypatch):
        monkeypatch.setattr(rc, "BacktestSerializer", lambda: _FakeSerializer(None))
        assert rc._generate_report("bt1", ["equity"]) is None

    def test_generate_report_valid(self, monkeypatch):
        payload = {
            "equity": [1.0, 1.1, 1.2],
            "trades": [{"ticker": "000001.SZ", "side": "buy", "quantity": 100,
                        "price": 10.0, "commission": 0.1}],
            "metadata": {"strategy": "我的策略", "start_date": "2024-01-01",
                         "end_date": "2024-12-31"},
        }
        monkeypatch.setattr(rc, "BacktestSerializer", lambda: _FakeSerializer(payload))
        html_out = rc._generate_report("bt1", ["equity", "performance", "trades", "drawdown"])
        assert isinstance(html_out, str)
        assert "FisherQuant 回测报告" in html_out
        assert "我的策略" in html_out
        # 累计收益应为 20.00%（nav 1.0 -> 1.2）
        assert "20.00%" in html_out

    def test_preview_report_no_id(self):
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-progress-bar")
        val, status, src = cb(1, None, ["equity"])
        assert val == 0 and status == "请输入回测ID"
        assert "<p>请输入回测ID</p>" == src

    def test_preview_report_success(self, monkeypatch):
        payload = {
            "equity": [1.0, 1.1, 1.2],
            "trades": [],
            "metadata": {"strategy": "我的策略", "start_date": "2024-01-01",
                         "end_date": "2024-12-31"},
        }
        monkeypatch.setattr(rc, "BacktestSerializer", lambda: _FakeSerializer(payload))
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-progress-bar")
        val, status, src = cb(1, "bt1", ["equity"])
        assert val == 100 and status == "预览已生成"
        assert "FisherQuant 回测报告" in src

    def test_download_report_no_id(self):
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-download")
        assert cb(1, None, "html", ["equity"]) is no_update

    def test_download_report_html(self, monkeypatch):
        payload = {
            "equity": [1.0, 1.1, 1.2], "trades": [],
            "metadata": {"strategy": "S", "start_date": "2024-01-01",
                         "end_date": "2024-12-31"},
        }
        monkeypatch.setattr(rc, "BacktestSerializer", lambda: _FakeSerializer(payload))
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-download")
        result = cb(1, "bt42", "html", ["equity"])
        # dcc.send_string / send_bytes 在本版本返回 dict（含 filename / content / type）
        fname = result["filename"] if isinstance(result, dict) else result.filename
        assert "bt42" in fname
        assert fname.endswith(".html")

    def test_download_report_pdf(self, monkeypatch):
        payload = {
            "equity": [1.0, 1.1, 1.2], "trades": [],
            "metadata": {"strategy": "S", "start_date": "2024-01-01",
                         "end_date": "2024-12-31"},
        }
        monkeypatch.setattr(rc, "BacktestSerializer", lambda: _FakeSerializer(payload))
        with capture_dash_callbacks() as app:
            rc.register_report_callbacks(app)
            cb = app.get_callback("report-download")
        result = cb(1, "bt42", "pdf", ["equity"])
        # weasyprint 可用 -> .pdf，否则回退 .html；都带 backtest_id
        fname = result["filename"] if isinstance(result, dict) else result.filename
        assert "bt42" in fname
        assert fname.endswith((".pdf", ".html"))


# --------------------------------------------------------------------------- #
# settings_callbacks
# --------------------------------------------------------------------------- #
class TestSettingsCallbacks:
    def test_register_and_key_callback(self):
        with capture_dash_callbacks() as app:
            sc.register_settings_callbacks(app)
            cb = app.get_callback("cfg-benchmark-mixed-config")
        assert callable(cb)
        assert app.callback_count() >= 5

    def test_save_params(self, monkeypatch):
        captured = []
        monkeypatch.setattr(sc, "_load_settings", lambda: {})
        monkeypatch.setattr(sc, "_save_settings", lambda d: captured.append(d))
        cb = _cb_by_arity(_register_only(sc.register_settings_callbacks), 7)
        result = cb(1, 0.0003, 5.0, 0.001, 1_000_000, 0.001, 0.02)
        assert result.children == "回测参数已保存"
        saved = captured[-1]
        assert saved["commission"] == 0.0003
        assert saved["min_commission"] == 5.0
        assert saved["capital"] == 1_000_000
        assert saved["risk_free_rate"] == 0.02

    def test_save_benchmark_simple(self, monkeypatch):
        captured = []
        monkeypatch.setattr(sc, "_load_settings", lambda: {})
        monkeypatch.setattr(sc, "_save_settings", lambda d: captured.append(d))
        cb = _cb_by_arity(_register_only(sc.register_settings_callbacks), 3)
        result = cb(1, "csi300", None)
        assert result.children == "基准配置已保存"
        assert captured[-1]["benchmark"]["type"] == "csi300"

    def test_save_benchmark_mixed_valid(self, monkeypatch):
        captured = []
        monkeypatch.setattr(sc, "_load_settings", lambda: {})
        monkeypatch.setattr(sc, "_save_settings", lambda d: captured.append(d))
        cb = _cb_by_arity(_register_only(sc.register_settings_callbacks), 3)
        result = cb(1, "mixed", '{"csi300": 0.6, "hs300": 0.4}')
        assert result.children == "基准配置已保存"
        assert captured[-1]["benchmark"]["weights"] == {"csi300": 0.6, "hs300": 0.4}

    def test_save_benchmark_mixed_invalid_json(self, monkeypatch):
        monkeypatch.setattr(sc, "_load_settings", lambda: {})
        monkeypatch.setattr(sc, "_save_settings", lambda d: None)
        cb = _cb_by_arity(_register_only(sc.register_settings_callbacks), 3)
        result = cb(1, "mixed", "{not json")
        assert isinstance(result, dbc.Alert)
        assert result.children == "混合基准权重JSON格式错误"
        assert result.color == "danger"

    def test_toggle_mixed_config(self):
        with capture_dash_callbacks() as app:
            sc.register_settings_callbacks(app)
            cb = app.get_callback("cfg-benchmark-mixed-config")
        assert cb("csi300") == {"display": "none"}
        assert cb("mixed") == {"display": "block"}

    def test_save_refresh(self, monkeypatch):
        captured = []
        monkeypatch.setattr(sc, "_load_settings", lambda: {})
        monkeypatch.setattr(sc, "_save_settings", lambda d: captured.append(d))
        with capture_dash_callbacks() as app:
            sc.register_settings_callbacks(app)
            # settings-save-status 的最后一个回调是 save_refresh（4 参）
            cb = app.get_callback("settings-save-status")
        result = cb(1, "0 18 * * *", 300, 60)
        assert result.children == "刷新策略已保存"
        assert captured[-1]["refresh"] == {
            "daily_cron": "0 18 * * *", "minute_interval": 300, "quote_interval": 60,
        }

    def test_refresh_log_missing_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "Path", _path_factory(tmp_path))
        with capture_dash_callbacks() as app:
            sc.register_settings_callbacks(app)
            cb = app.get_callback("cfg-log-content")
        assert cb(1, ["INFO", "ERROR"]) == "日志文件不存在"

    def test_refresh_log_filtered(self, monkeypatch, tmp_path):
        log = tmp_path / "app.log"
        log.write_text(
            "INFO starting\nERROR boom\nDEBUG trace\nWARNING slow\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sc, "Path", _path_factory(tmp_path))
        with capture_dash_callbacks() as app:
            sc.register_settings_callbacks(app)
            cb = app.get_callback("cfg-log-content")
        out = cb(1, ["ERROR", "WARNING"])
        assert "ERROR boom" in out
        assert "WARNING slow" in out
        assert "INFO starting" not in out
        assert "DEBUG trace" not in out


def _register_only(register_fn):
    """仅注册、不取回，供 _cb_by_arity 在 settings 多回调同 id 场景使用。"""
    with capture_dash_callbacks() as app:
        register_fn(app)
    return app


def _path_factory(tmp_path):
    real = pathlib.Path

    class _Redir:
        def __init__(self, p):
            self._p = p

        def exists(self):
            return self._p.exists()

        def read_text(self, *a, **k):
            return self._p.read_text(*a, **k)

    def factory(*args, **kwargs):
        s = str(args[0]) if args else ""
        if s == "logs/app.log":
            return _Redir(tmp_path / "app.log")
        return real(*args, **kwargs)

    return factory


# --------------------------------------------------------------------------- #
# home_callbacks
# --------------------------------------------------------------------------- #
class TestHomeCallbacks:
    def test_register_and_key_callback(self):
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("recent-backtests")
        assert callable(cb)
        assert app.callback_count() >= 3

    def test_update_home_dashboard_wrong_path(self):
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("recent-backtests")
        result = cb("/data-center")
        assert result == (no_update, no_update, no_update, no_update, no_update, no_update)

    def test_update_home_dashboard_stats(self, monkeypatch):
        class _Svc:
            def get_cache_stats(self):
                return {"total": 120, "a_share": 100, "hk": 20,
                        "records": 5000, "last_update": "2024-06-01 10:00"}
        monkeypatch.setattr(hc, "get_data_service", lambda: _Svc())
        monkeypatch.setattr(hc, "_build_recent_backtests", lambda: "最近回测列表")
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("recent-backtests")
        recent, tickers, ashare, hk, records, last = cb("/home")
        assert recent == "最近回测列表"
        assert tickers == "120" and ashare == "100" and hk == "20"
        assert records == "5000"
        assert last == "最近更新: 2024-06-01 10:00"

    def test_quick_action_handler(self, monkeypatch):
        # 直接替换模块级 dash 引用，注入假 callback_context
        monkeypatch.setattr(
            hc, "dash",
            SimpleNamespace(callback_context=SimpleNamespace(
                triggered=[{"prop_id": "quick-backtest.n_clicks"}])))
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("quick-nav-location")
        assert cb(None, None, 1) == "/backtest-center"

    def test_quick_action_handler_no_trigger(self, monkeypatch):
        monkeypatch.setattr(
            hc, "dash",
            SimpleNamespace(callback_context=SimpleNamespace(triggered=[])))
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("quick-nav-location")
        assert cb(None, None, None) is no_update

    def test_auto_load_indicator(self, monkeypatch):
        class _Svc:
            def get_progress(self):
                return {"phase": "initial_load", "current": 3, "total": 10}
        monkeypatch.setattr(hc, "get_auto_load_service", lambda: _Svc())
        with capture_dash_callbacks() as app:
            hc.register_home_callbacks(app)
            cb = app.get_callback("auto-load-indicator")
        res = cb(1)
        assert isinstance(res, html.Div)
        assert "已加载 3/10" in str(res.children)

    def test_build_recent_backtests(self, monkeypatch):
        rows = [[1, "策略A", "000001.SZ", 100, "x", "y", "完成"]]
        monkeypatch.setattr(hc, "DuckDBManager", lambda: _FakeDuck(rows))
        res = hc._build_recent_backtests()
        assert isinstance(res, dbc.ListGroup)
        # 列表项包含策略名与状态
        blob = str(res.children)
        assert "策略A" in blob and "完成" in blob

    def test_build_recent_backtests_empty(self, monkeypatch):
        monkeypatch.setattr(hc, "DuckDBManager", lambda: _FakeDuck([]))
        assert hc._build_recent_backtests() == "暂无回测记录"
