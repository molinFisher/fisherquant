"""Phase 3 单元级测试：data / data_cache / data_export / quote / strategy_crud /
strategy_wizard 六个回调模块。

通过 tests/helpers/dash_harness.capture_dash_callbacks 捕获 @app.callback /
@callback 闭包，直接注入 mock 依赖后调用，并断言关键组件内容与数值。

依赖隔离策略：
  - 数据服务：monkeypatch fisher.dash_app.services.get_data_service 或各模块的
    get_data_service / get_strategy_service（按其 import 时机），返回 FakeService。
  - 行情 DB：monkeypatch 各模块的 DuckDBManager 为 FakeDuckDB（内存 polars DataFrame）。
  - 触发上下文：monkeypatch dash.ctx / dash.callback_context 为 CtxStub。
  - 文件路径：_save_watchlist 的 QB_WATCHLIST_FILE 指向 tmp_path，避免真实磁盘写入。
  - 时间：check_trading_hours 通过替换 datetime.datetime 固定当前时间。

注意：harness 仅把 @callback 的第一个位置参数当作输出 id 捕获，因此多 Output 的回调
（如 handle_import / handle_wizard_navigation / handle_template）不会按子输出 id 注册。
本文件统一用 _nth(app, n) 按「注册顺序」精确取回目标闭包（单个模块注册时顺序即源码顺序）。

禁止真实网络 / 真实磁盘数据库写；校验关键文本或数值，而非仅 isinstance / no_crash。
"""
import base64
import datetime as _dtmod

import polars as pl
import pytest
from dash import html, dash_table, no_update

try:
    import xlsxwriter  # noqa: F401  # polars 写 Excel 的可选依赖
    HAVE_XLSXWRITER = True
except ImportError:
    HAVE_XLSXWRITER = False

from tests.helpers.dash_harness import capture_dash_callbacks

from fisher.dash_app.callbacks import data_callbacks
from fisher.dash_app.callbacks import data_cache_callbacks
from fisher.dash_app.callbacks import data_export_callbacks
from fisher.dash_app.callbacks import quote_callbacks
from fisher.dash_app.callbacks import strategy_crud_callbacks
from fisher.dash_app.callbacks import strategy_wizard_callbacks


# --------------------------------------------------------------------------- #
# 通用假依赖
# --------------------------------------------------------------------------- #
class FakeService:
    """一个可配置的数据/策略服务替身，覆盖 6 个模块用到的全部方法。"""

    def __init__(self, **kwargs):
        self.data = kwargs
        self.calls = []

    def search_symbols(self, query):
        return self.data.get("search_symbols", [])

    def fetch_bars(self, symbols, start, end, data_type, period):
        self.calls.append(("fetch_bars", list(symbols)))
        return self.data.get("fetch_bars", {})

    def get_cached_table(self, market_filter="all", text_filter=""):
        if self.data.get("raise_cached"):
            raise RuntimeError("boom")
        return self.data.get("cached_table", [])

    def delete_symbols(self, tickers):
        self.calls.append(("delete_symbols", list(tickers)))

    def delete_symbols_by_type(self, tickers, data_type):
        self.calls.append(("delete_symbols_by_type", list(tickers), data_type))

    @property
    def _db(self):
        return self.data.get("_db")

    def export_json(self, name):
        return self.data.get("export_json", "")

    def import_json(self, text):
        return self.data.get("import_json", {"status": "ok"})

    def list_strategies(self):
        if "list_strategies" in self.data:
            return self.data["list_strategies"]
        return list(self.data.get("strategies", {}).values())

    def get_strategy(self, name):
        return self.data.get("strategies", {}).get(name)

    def save_strategy(self, cfg):
        self.calls.append(("save_strategy", cfg))

    def delete_strategy(self, name):
        self.calls.append(("delete_strategy", name))


class FakeDuckDB:
    """DuckDBManager 替身：从不同 SQL 返回内存 polars DataFrame，避免真实磁盘库。

    distinct_rows / quote_rows 直接以 polars 友好的结构传入（字典构造出正确列）。
    """

    def __init__(self, distinct_rows=None, quote_rows=None):
        self._distinct = distinct_rows
        self._quote = quote_rows
        self._initialized = True

    def query_df(self, sql, params=None):
        if "DISTINCT ticker" in sql:
            return pl.DataFrame(self._distinct)
        return pl.DataFrame(self._quote)


class CtxStub:
    """模拟 dash.ctx / dash.callback_context：仅暴露 triggered 与 states。"""

    def __init__(self, triggered=None, states=None):
        self.triggered = triggered or []
        self.states = states or {}


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _nth(app, n):
    """按注册顺序取回第 n 个被捕获的回调闭包（单个模块注册时即源码顺序）。"""
    return app.all_callbacks()[n]


def _text(node, out=None):
    """递归抽取 dash 组件树中的文本，用于断言关键文案。"""
    if out is None:
        out = []
    if node is None:
        return out
    if isinstance(node, str):
        out.append(node)
        return out
    if isinstance(node, (list, tuple)):
        for c in node:
            _text(c, out)
        return out
    children = getattr(node, "children", None)
    if children is not None:
        if isinstance(children, (list, tuple)):
            for c in children:
                _text(c, out)
        else:
            _text(children, out)
    return out


def _patch_now(monkeypatch, dt_tuple):
    """固定 datetime.datetime.now() 为给定时间元组 (y,m,d,h,mi,s)。"""
    real = _dtmod.datetime

    class _Fixed(_dtmod.datetime):
        @classmethod
        def now(cls, tz=None):
            return real(*dt_tuple)

    monkeypatch.setattr("datetime.datetime", _Fixed)


def _patch_dash_ctx(monkeypatch, triggered=None, states=None):
    monkeypatch.setattr("dash.ctx", CtxStub(triggered=triggered, states=states))


def _patch_callback_context(monkeypatch, triggered):
    monkeypatch.setattr("dash.callback_context", CtxStub(triggered=triggered))


# =========================================================================== #
# 1) data_callbacks
# =========================================================================== #
class TestDataCallbacks:
    """数据查询 Tab 重设计（PRD v1.1）：改用 by_output 取回调，消除顺序依赖。"""

    def test_registers(self):
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
        assert app.callback_count() >= 6
        assert callable(app.by_output("search-status"))       # search_symbols
        assert callable(app.by_output("fetch-results"))        # fetch_data
        assert callable(app.by_output("selected-symbols-store"))  # sync_selected_pool
        assert callable(app.by_output("fetch-guard-hint"))     # guard_fetch_button

    def test_search_symbols_too_short(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("search-status")
        # 重设计：回调返回 3 元组（options / status / store）
        opts, status, store = cb("a")
        assert opts == [] and store == []
        assert "至少" in "".join(_text(status))

    def test_search_symbols_matches(self, monkeypatch):
        fake = FakeService(search_symbols=[
            {"label": "600519 贵州茅台", "value": "600519.SH",
             "code": "600519", "name": "贵州茅台", "market": "a_share"}])
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("search-status")
        opts, status, store = cb("6005")
        assert opts and opts[0]["value"] == "600519.SH"
        assert "贵州茅台" in opts[0]["label"]
        assert "找到 1 个结果" in "".join(_text(status))
        assert store == fake.data["search_symbols"]  # 完整结构写入 store

    def test_search_symbols_exception(self, monkeypatch):
        class _Boom(FakeService):
            def search_symbols(self, q):
                raise RuntimeError("db down")
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: _Boom())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("search-status")
        opts, status, store = cb("600519")
        # R-31：不再暴露技术堆栈，改为友好文案
        assert opts == [] and store == []
        assert "暂时不可用" in "".join(_text(status))

    def test_search_multi_code_paste(self, monkeypatch):
        """FR-3：粘贴多代码 → 逐 token 命中合并；未收录标灰禁用。"""
        dict_data = {
            "600519": {"label": "600519 贵州茅台", "value": "600519.SH",
                       "code": "600519", "name": "贵州茅台", "market": "a_share"},
            "000001": {"label": "000001 平安银行", "value": "000001.SZ",
                       "code": "000001", "name": "平安银行", "market": "a_share"},
            "300750": {"label": "300750 宁德时代", "value": "300750.SZ",
                       "code": "300750", "name": "宁德时代", "market": "a_share"},
        }

        class _Dict(FakeService):
            def search_symbols(self, q):
                hit = dict_data.get(q)
                return [hit] if hit else []

        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: _Dict())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("search-status")
        opts, status, store = cb("600519 000001, 300750\n999999")
        values = [o["value"] for o in opts]
        assert "600519.SH" in values and "000001.SZ" in values and "300750.SZ" in values
        assert len(store) == 3
        # 未收录 token 标灰禁用
        miss = [o for o in opts if o.get("disabled")]
        assert len(miss) == 1 and "999999" in miss[0]["label"] and "未收录" in miss[0]["label"]
        assert "未收录 1 个" in "".join(_text(status))

    def test_fetch_data_is_not_generator(self, monkeypatch):
        """回归：fetch_data 不得是生成器函数。

        Dash background 回调不支持生成器（diskcache pickle 失败导致
        取数结果永远不返回，2026-07-28 线上 bug）。
        """
        import inspect
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("fetch-results")
        assert not inspect.isgeneratorfunction(cb)

    def test_fetch_data_no_symbols(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("fetch-results")
        final = cb(1, [], "2024-01-01", "2024-02-01", "daily", "")
        assert "勾选标的" in final[0]

    def test_fetch_data_success(self, monkeypatch):
        fake = FakeService(fetch_bars={"600519.SH": {"status": "ok", "count": 5}})
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("fetch-results")
        pool = [{"value": "600519.SH", "code": "600519",
                 "name": "贵州茅台", "market": "a_share"}]
        final = cb(1, pool, "2024-01-01", "2024-02-01", "daily", "")
        assert "成功 1" in final[0]
        assert "✓ 600519.SH: 5条记录" in "".join(_text(final[1]))
        # 进度条已按产品要求移除（回调仅输出 fetch-status / fetch-results 两项）
        assert len(final) == 2
        assert ("fetch_bars", ["600519.SH"]) in fake.calls

    def test_fetch_data_financials_skips_hk(self, monkeypatch):
        """产品决策：财务数据仅支持 A 股——池中港股跳过且不调用服务。"""
        fake = FakeService(fetch_bars={"600519.SH": {"status": "ok", "count": 0}})
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("fetch-results")
        pool = [
            {"value": "600519.SH", "code": "600519", "name": "贵州茅台",
             "market": "a_share"},
            {"value": "00700.HK", "code": "00700", "name": "腾讯控股",
             "market": "hk_connect"},
        ]
        final = cb(1, pool, "2024-01-01", "2024-02-01", "financials", "")
        txt = "".join(_text(final[1]))
        assert "⊘ 00700.HK" in txt and "仅支持 A 股" in txt
        assert ("fetch_bars", ["600519.SH"]) in fake.calls
        assert all(c[1] != ["00700.HK"] for c in fake.calls)  # 港股未触发取数

    def test_toggle_minute_period(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = app.by_output("minute-period-container")
        assert cb("minute") == {"display": "block"}
        assert cb("daily") == {"display": "none"}


# =========================================================================== #
# 2) data_cache_callbacks
# =========================================================================== #
class FakeCatalogService:
    """cache_catalog 目录服务替身（V1.4 目录页数据源切换后使用）。"""

    def __init__(self, summary=None):
        self.summary = summary or []
        self.calls = []

    def get_cache_summary(self, market=None, data_types=None, text=None):
        self.calls.append(("get_cache_summary", market, list(data_types or []), text))
        return self.summary


class FakeCatalog:
    """quote_callbacks 用的轻量 CacheCatalogService 替身（IC-3 / FR-4.3 / FR-3.3）。"""

    def __init__(self, *a, **k):
        self._tickers = {"600519.SH", "000001.SZ"}
        self._has = {"600519.SH": True, "000001.SZ": False}

    def get_tickers_with_data(self):
        return set(self._tickers)

    def get_coverage_for_tickers(self, tickers):
        return {t: {"ticker": t, "has_realtime": self._has.get(t, False),
                    "has_minute": False, "has_daily": True, "has_adj": False}
                for t in tickers if t in self._tickers}

    def has_any_data(self, ticker):
        return ticker in self._tickers


def _summary_row(ticker="600519.SH", **kw):
    row = {
        "ticker": ticker, "name": "贵州茅台", "market": "a_share",
        "has_daily": True, "has_minute": False, "has_realtime": False,
        "has_adj": False, "has_financials": False,
        "daily_start": "2024-01-01", "daily_end": "2024-02-01",
        "realtime_ts": None, "daily_rows": 10, "minute_rows": 0,
    }
    row.update(kw)
    return row


class TestDataCacheCallbacks:
    def test_registers(self):
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
        assert app.callback_count() >= 3
        assert callable(_nth(app, 0))

    def test_empty_cached_table_helper(self):
        el = data_cache_callbacks._empty_cached_table()
        assert isinstance(el, html.Div)
        assert "暂无缓存数据" in "".join(_text(el))

    def test_coverage_markdown_badges(self):
        """U-1：覆盖度徽标 ✓绿 ✗灰，hover 出类型名 + 边界日期。Task #24 含财务第 5 类。"""
        md = data_cache_callbacks._coverage_markdown(_summary_row())
        assert "日✓" in md and "分✗" in md and "实✗" in md and "复✗" in md and "财✗" in md
        assert "#28a745" in md          # 有数据 → 绿
        assert "2024-01-01 ~ 2024-02-01" in md  # hover 边界
        # 财务已缓存：财✓ + hover 报告期
        md2 = data_cache_callbacks._coverage_markdown(
            _summary_row(has_financials=True, fin_report_end="2024-12-31"))
        assert "财✓" in md2 and "2024-12-31" in md2

    def test_force_refresh_cached_not_active(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService())
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 0)
        assert cb(1, "tab-other") is no_update

    def test_force_refresh_cached_with_rows(self, monkeypatch):
        fake = FakeCatalogService(summary=[_summary_row(ticker="000001.SZ")])
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "tab-cached")
        assert isinstance(res, dash_table.DataTable)
        assert res.id == "cached-data-table"
        assert res.data[0]["ticker"] == "000001.SZ"
        assert res.data[0]["daily_rows"] == 10

    def test_render_cached_table_not_active(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService())
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        assert cb("tab-live", "all", [], "", 0, 0) is no_update

    def test_render_cached_table_with_rows(self, monkeypatch):
        fake = FakeCatalogService(summary=[_summary_row()])
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        res = cb("tab-cached", "all", [], "", 1, 1)
        assert isinstance(res, dash_table.DataTable)
        assert res.id == "cached-data-table"
        assert res.data[0]["ticker"] == "600519.SH"
        # 覆盖度列为 markdown 徽标
        cov_col = [c for c in res.columns if c["id"] == "coverage"]
        assert cov_col and cov_col[0].get("presentation") == "markdown"

    def test_render_cached_table_type_filter_passthrough(self, monkeypatch):
        """FR-8.2：数据类型多选透传给 get_cache_summary（AND 语义在服务层）。"""
        fake = FakeCatalogService(summary=[_summary_row()])
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        cb("tab-cached", "a_share", ["daily", "minute"], "茅台", 1, 1)
        assert fake.calls[-1] == ("get_cache_summary", "a_share",
                                  ["daily", "minute"], "茅台")

    def test_render_cached_table_empty(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService(summary=[]))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        res = cb("tab-cached", "all", [], "", 1, 1)
        assert isinstance(res, html.Div)
        assert "暂无缓存数据" in "".join(_text(res))

    def test_poll_updates_data_without_rebuild(self, monkeypatch):
        """回归测试：auto-load 轮询(3s)只应更新 cached-data-table.data，
        绝不可重建 cached-table-container 的 children（重建会把 page_current 重置回第 1 页）。

        关键断言：
          - 轮询回调返回的是「行数据列表」，不是 DataTable / 容器，因此不重建组件；
          - 数据变化时仍返回最新行（保证自动加载新增标的会刷新出来）；
          - 不在缓存 tab 时返回 no_update，避免无谓更新。
        """
        summary = [_summary_row(ticker="600519.SH"),
                   _summary_row(ticker="000001.SZ", daily_rows=8)]
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService(summary=summary))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            # 轮询回调按注册顺序是第 4 个（force_refresh / render / delete / poll）
            poll = _nth(app, 3)
        # 不在缓存 tab → no_update
        assert poll(0, "tab-query", "all", [], "") is no_update
        # 在缓存 tab → 返回行数据列表（不是 DataTable / html.Div）
        out = poll(0, "tab-cached", "all", [], "")
        assert isinstance(out, list)
        assert [r["ticker"] for r in out] == ["600519.SH", "000001.SZ"]
        # 数据变化（自动加载新增标的）→ 返回最新行，仍是 list（仍不重建组件）
        changed = summary + [_summary_row(ticker="300750.SZ", daily_rows=3)]
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService(summary=changed))
        out2 = poll(1, "tab-cached", "all", [], "")
        assert isinstance(out2, list)
        assert any(r["ticker"] == "300750.SZ" for r in out2)

    def test_confirm_delete_full_row(self, monkeypatch):
        """FR-8.3：确认删除（整行）走 delete_symbols 并关闭 Modal。"""
        fake = FakeService()
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: fake)
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService(summary=[_summary_row()]))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 2)
        # 未选中 → 不删除
        out = cb(1, None, None, "all", "all", [], "")
        assert out[0] is no_update
        res, is_open = cb(1, [0], [{"ticker": "600519"}, {"ticker": "000001"}],
                          "all", "all", [], "")
        assert isinstance(res, dash_table.DataTable)
        assert is_open is False
        assert ("delete_symbols", ["600519"]) in fake.calls

    def test_confirm_delete_by_type(self, monkeypatch):
        """FR-1.5：按类型删除走 delete_symbols_by_type（服务层联动 has_*）。"""
        fake = FakeService()
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: fake)
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: FakeCatalogService(summary=[]))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 2)
        cb(1, [0], [{"ticker": "600519.SH"}], "minute", "all", [], "")
        assert ("delete_symbols_by_type", ["600519.SH"], "minute") in fake.calls
        assert ("delete_symbols", ["600519.SH"]) not in fake.calls

    def test_delete_modal_confirm_text(self):
        """U-4：确认文案明示数据类型与影响范围。"""
        body = data_cache_callbacks._delete_confirm_text(
            ["600519.SH", "000001.SZ"], "minute")
        text = "".join(_text(body))
        assert "2 个标的" in text
        assert "分钟线" in text and "不受影响" in text
        body_all = data_cache_callbacks._delete_confirm_text(["600519.SH"], "all")
        text_all = "".join(_text(body_all))
        assert "全部缓存数据" in text_all and "不可恢复" in text_all

    def test_consume_focus_presets_and_clears(self):
        """FR-4.2 / IC-2 / U-2：看板跳转过来时预置筛选 + 激活 tab-cached，消费后清空 ?focus=。"""
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            # consume_focus 是最后注册的第 6 个回调
            cb = _nth(app, 5)
        # ?tab=tab-cached&focus=<ticker> → 预置筛选值 + 激活 tab + 清空 focus
        f, tab, new_search = cb("?tab=tab-cached&focus=600519.SH", "/data-center")
        assert f == "600519.SH"
        assert tab == "tab-cached"
        assert new_search == "?tab=tab-cached"
        # 二次触发（focus 已清）→ 全部 no_update，避免循环
        assert cb("?tab=tab-cached", "/data-center") == (no_update, no_update, no_update)
        # 非 data-center 页面 → 忽略
        assert cb("?tab=tab-cached&focus=600519.SH", "/market-watch") == (
            no_update, no_update, no_update)
        # 无 focus → 忽略
        assert cb("?tab=tab-query", "/data-center") == (no_update, no_update, no_update)

    def test_batch_add_to_board_writes_watchlist_and_redirects(self, monkeypatch, tmp_path):
        """IC-1 / FR-3.1 / FR-7.5：批量加入看板写自选 + 置 auto_load_enabled + 跳转看板。

        batch_add_to_board 是第 7 个注册的回调（index 6）。
        """
        class _CatalogWithAutoLoad(FakeCatalogService):
            def __init__(self, summary=None):
                super().__init__(summary)
                self.auto_enabled = []

            def set_auto_load_enabled(self, ticker, enabled):
                self.auto_enabled.append((ticker, enabled))

        fake = _CatalogWithAutoLoad(summary=[
            _summary_row(ticker="600519.SH"),
            _summary_row(ticker="000001.SZ", daily_rows=8),
        ])
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: fake)
        # 看板自选读写落 tmp，避免污染项目磁盘
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE",
                            str(tmp_path / "watchlist.json"))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 6)
        # 无点击 → 不动作
        assert cb(None, "all", [], "") == (no_update, no_update)
        # 点击 → 写自选 + 置 auto_load_enabled + 跳转看板定位首标
        pathname, search = cb(1, "all", [], "")
        assert pathname == "/market-watch"
        assert search == "?focus=600519.SH"
        assert ("600519.SH", True) in fake.auto_enabled
        assert ("000001.SZ", True) in fake.auto_enabled
        # 验证 watchlist 已真实写入 tmp 文件
        import json
        from pathlib import Path
        wl = json.loads(Path(tmp_path / "watchlist.json").read_text(encoding="utf-8"))
        assert set(wl) == {"600519.SH", "000001.SZ"}

    def test_batch_add_to_board_no_rows_noop(self, monkeypatch):
        """空目录（无缓存标的）点击批量加入 → 不跳转、不写。"""
        fake = FakeCatalogService(summary=[])
        monkeypatch.setattr(data_cache_callbacks, "get_cache_catalog_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 6)
        assert cb(1, "all", [], "") == (no_update, no_update)


# =========================================================================== #
# 3) data_export_callbacks
# =========================================================================== #
class TestDataExportCallbacks:
    def test_registers(self):
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
        assert app.callback_count() >= 2
        assert callable(_nth(app, 0))
        assert callable(_nth(app, 1))

    def _rows(self):
        return [
            {"ticker": "600519", "market": "a_share", "records": 10,
             "start_date": "2024-01-01", "end_date": "2024-02-01"},
            {"ticker": "000001", "market": "a_share", "records": 8,
             "start_date": "2023-01-01", "end_date": "2023-02-01"},
        ]

    def test_export_empty(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=[]))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        assert cb(1, "csv", "", None, None) is None

    def test_export_csv(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=self._rows()))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "csv", "", None, None)
        assert isinstance(res, dict)
        assert res["filename"] == "fisherquant_data.csv"
        assert "ticker" in res["content"] and "600519" in res["content"]

    def test_export_csv_symbol_filter(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=self._rows()))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "csv", "000001", None, None)
        assert "000001" in res["content"]
        assert "600519" not in res["content"]

    def test_export_csv_start_date_filter(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=self._rows()))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "csv", "", "2024-01-01", None)
        assert "600519" in res["content"]
        assert "000001" not in res["content"]

    def test_export_xlsx(self, monkeypatch):
        if not HAVE_XLSXWRITER:
            pytest.skip("xlsxwriter 未安装（polars 写 Excel 的可选依赖），无法隔离")
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=self._rows()))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "xlsx", "", None, None)
        assert res["filename"] == "fisherquant_data.xlsx"
        # send_bytes 默认 base64 编码，content 为字符串（非空即可）
        assert isinstance(res["content"], str) and res["content"]

    def test_export_get_cached_raises(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService(raise_cached=True))
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 0)
        assert cb(1, "csv", "", None, None) is None

    def test_fetch_adj_factor_empty_symbol(self, monkeypatch):
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 1)
        res = cb(1, "")
        assert isinstance(res, html.Div)
        assert "请输入标的代码" in "".join(_text(res))

    def test_fetch_adj_factor_unadjusted(self, monkeypatch):
        db = FakeDuckDB(quote_rows=[
            {"trade_date": "2024-01-02", "adj_factor": 1.0},
            {"trade_date": "2024-01-03", "adj_factor": 1.0},
        ])
        fake = FakeService(cached_table=[{"ticker": "600519"}], _db=db)
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 1)
        res = cb(1, "600519")
        txt = "".join(_text(res))
        assert "未复权" in txt and "600519" in txt

    def test_fetch_adj_factor_adjusted(self, monkeypatch):
        db = FakeDuckDB(quote_rows=[
            {"trade_date": "2024-01-02", "adj_factor": 1.0},
            {"trade_date": "2024-01-03", "adj_factor": 2.0},
        ])
        fake = FakeService(cached_table=[{"ticker": "600519"}], _db=db)
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 1)
        res = cb(1, "600519")
        assert "已复权" in "".join(_text(res))

    def test_fetch_adj_factor_no_rows(self, monkeypatch):
        db = FakeDuckDB(quote_rows=[])
        fake = FakeService(cached_table=[{"ticker": "600519"}], _db=db)
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 1)
        assert "未找到该标的的数据" in "".join(_text(cb(1, "600519")))

    def test_fetch_adj_factor_db_error(self, monkeypatch):
        class _BrokenDB:
            def query_df(self, sql, params=None):
                raise RuntimeError("db")
        fake = FakeService(cached_table=[{"ticker": "600519"}], _db=_BrokenDB())
        monkeypatch.setattr(data_export_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_export_callbacks.register_data_export_callbacks(app)
            cb = _nth(app, 1)
        assert "查询失败" in "".join(_text(cb(1, "600519")))


# =========================================================================== #
# 4) quote_callbacks
# =========================================================================== #
class TestQuoteCallbacks:
    def test_registers(self):
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
        assert app.callback_count() >= 4
        assert callable(_nth(app, 0))

    def test_fetch_quote_data(self, monkeypatch):
        db = FakeDuckDB(quote_rows=[
            {"close": 110.0, "volume": 1000, "trade_date": "2024-01-03"},
            {"close": 100.0, "volume": 2000, "trade_date": "2024-01-02"},
        ])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        data = quote_callbacks._fetch_quote_data(["600519.SZ"])
        assert data[0]["code"] == "600519.SZ"
        assert data[0]["name"] == "600519"
        assert data[0]["last_price"] == "110.00"
        assert data[0]["change_pct"] == "+10.00%"
        assert data[0]["volume"] == "1,000"
        assert data[0]["change_raw"] == 10.0

    def test_fetch_quote_data_prev_zero(self, monkeypatch):
        db = FakeDuckDB(quote_rows=[
            {"close": 110.0, "volume": 1000, "trade_date": "2024-01-03"},
            {"close": 0.0, "volume": 2000, "trade_date": "2024-01-02"},
        ])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        data = quote_callbacks._fetch_quote_data(["600519.SZ"])
        assert data[0]["change_raw"] == 0

    def test_build_quote_table(self):
        data = [{"code": "600519", "name": "600519", "last_price": "110.00",
                 "change_pct": "+1.00%", "volume": "1,000", "change_raw": 1.0}]
        tbl = quote_callbacks._build_quote_table(data)
        assert isinstance(tbl, dash_table.DataTable)
        assert tbl.data == data

    def test_fetch_quote_data_goto_cache_link(self, monkeypatch):
        """FR-4.2 / IC-2：每行带去缓存跳转链接，锚向 ?tab=tab-cached&focus=<ticker>。"""
        db = FakeDuckDB(quote_rows=[
            {"close": 110.0, "volume": 1000, "trade_date": "2024-01-03"},
            {"close": 100.0, "volume": 2000, "trade_date": "2024-01-02"},
        ])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        data = quote_callbacks._fetch_quote_data(["600519.SZ"])
        assert data[0]["goto_cache"] == (
            "[去缓存](/data-center?tab=tab-cached&focus=600519.SZ)")

    def test_build_quote_table_goto_column(self):
        data = [{"code": "600519", "name": "600519", "last_price": "110.00",
                 "change_pct": "+1.00%", "volume": "1,000", "change_raw": 1.0,
                 "goto_cache": "[去缓存](/data-center?tab=tab-cached&focus=600519)"}]
        tbl = quote_callbacks._build_quote_table(data)
        goto_col = next(c for c in tbl.columns if c["id"] == "goto_cache")
        assert goto_col["presentation"] == "markdown"
        # 带 goto_cache 时 data 形状应保持一致（不破坏其余断言）
        assert tbl.data == data

    def test_load_qb_symbols(self, monkeypatch):
        db = FakeDuckDB(distinct_rows={"ticker": ["600519", "000001"]})
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        # IC-3：下拉选项来源改为 cache_catalog（已缓存宇宙），而非 bars_daily DISTINCT
        monkeypatch.setattr(quote_callbacks, "CacheCatalogService",
                            lambda *a, **k: FakeCatalog())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 0)
        res = cb("/market-watch")
        assert res == [{"label": "000001.SZ", "value": "000001.SZ"},
                       {"label": "600519.SH", "value": "600519.SH"}]

    def test_update_watchlist_add(self, monkeypatch, tmp_path):
        db = FakeDuckDB(quote_rows=[
            {"close": 110.0, "volume": 1000, "trade_date": "2024-01-03"}])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE",
                            str(tmp_path / "watchlist.json"))
        monkeypatch.setattr(quote_callbacks, "ctx",
                            CtxStub(triggered=[{"prop_id": "qb-add-btn.n_clicks"}]))
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 1)
        watchlist, tbl = cb(1, None, None, "600519.SZ", None, "none")
        assert watchlist == ["600519.SZ"]
        assert isinstance(tbl, dash_table.DataTable)
        # 验证确实写入了 tmp 文件（真实读写逻辑，不污染项目磁盘）
        assert (tmp_path / "watchlist.json").exists()

    def test_update_watchlist_empty(self, monkeypatch, tmp_path):
        db = FakeDuckDB(quote_rows=[])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE",
                            str(tmp_path / "watchlist.json"))
        monkeypatch.setattr(quote_callbacks, "ctx", CtxStub(
            triggered=[{"prop_id": "qb-manual-refresh.n_clicks"}]))
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 1)
        watchlist, tbl = cb(None, 1, None, None, None, "none")
        assert watchlist == []
        assert isinstance(tbl, html.Div)
        assert "自选列表为空" in "".join(_text(tbl))

    def test_toggle_auto_refresh(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 2)
        assert cb(True) is False
        assert cb(False) is True

    def test_check_trading_hours_trading(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 3, 10, 0, 0))  # 周三盘中
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/market-watch", None) is True

    def test_check_trading_hours_lunch_closed(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 3, 12, 30, 0))  # 周三午休（修复前误判为开市）
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/market-watch", None) is False

    def test_check_trading_hours_weekend_closed(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 6, 10, 0, 0))  # 周六
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/market-watch", None) is False

    def test_check_trading_hours_after_close(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 3, 16, 0, 0))  # 收盘后
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/market-watch", None) is False

    def test_fetch_quote_data_daily_fallback_badge(self, monkeypatch):
        """FR-6.2 / 验收 15：无实时快照 → 降级日频 + 徽标标记「实时✗(日频)」。"""
        db = FakeDuckDB(quote_rows=[
            {"close": 110.0, "volume": 1000, "trade_date": "2024-01-03"},
            {"close": 100.0, "volume": 2000, "trade_date": "2024-01-02"}])
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        data = quote_callbacks._fetch_quote_data(["600519.SZ"])
        assert data[0]["daily_fallback"] is True
        assert "日频" in data[0]["realtime_status"]
        # 目录读取失败（测试替身）时覆盖度徽标为空
        assert data[0]["coverage"] == ""

    def test_quote_row_snapshot_source(self):
        """FR-6.1：有实时快照 → 取 last_price/change_pct/volume，徽标「实时✓」。"""
        row = quote_callbacks._quote_row(
            "600519.SH",
            {"last_price": 11.0, "change_pct": 1.5, "volume": 500},
            {"has_realtime": True, "has_daily": True, "has_minute": False, "has_adj": False})
        assert row["last_price"] == "11.00"
        assert row["change_pct"] == "+1.50%"
        assert row["daily_fallback"] is False
        assert "实时✓" in row["realtime_status"]
        assert "实✓" in row["coverage"] and "日✓" in row["coverage"]

    def test_render_health(self, monkeypatch):
        """FR-4.3：健康度汇总 + 批量去缓存入口。"""
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 4)
        res = cb(["600519.SH", "000001.SZ"])
        text = "".join(_text(res))
        assert "实时覆盖 0/2" in text
        assert "批量去缓存补齐" in text

    def test_consume_focus_board_reorder_and_clear(self, monkeypatch):
        """FR-3.3 / IC-1 / U-2：聚焦标的置顶 + 消费后清空 ?focus=。"""
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        monkeypatch.setattr(quote_callbacks, "CacheCatalogService",
                            lambda *a, **k: FakeCatalog())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 5)
        wl, tbl, new_search, chart = cb("?focus=600519.SH", "/market-watch", ["000001.SZ"])
        assert wl[0] == "600519.SH" and wl == ["600519.SH", "000001.SZ"]
        assert new_search == ""  # focus 已清除
        assert chart == "600519.SH"  # FR-2.3：图表标的设为焦点
        assert isinstance(tbl, dash_table.DataTable)

    def test_consume_focus_board_dead_symbol_rejected(self, monkeypatch):
        """FR-5.3：死标（无缓存）聚焦时不入自选，仅清除参数。"""
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())

        class DeadCatalog:
            def __init__(self, *a, **k): pass
            def has_any_data(self, t): return False

        monkeypatch.setattr(quote_callbacks, "CacheCatalogService",
                            lambda *a, **k: DeadCatalog())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 5)
        wl, tbl, new_search, chart = cb("?focus=999999.SH", "/market-watch", ["000001.SZ"])
        assert wl is no_update and tbl is no_update
        assert new_search == ""
        assert chart is no_update


    # ----------------------------------------------------------------- #
    # Task #20：存量 watchlist pruning 清死标（FR-5.3 / T-4）
    # ----------------------------------------------------------------- #
    def test_prune_watchlist_removes_dead_keeps_live(self, monkeypatch):
        """FR-5.3 / T-4：_prune_watchlist 移除死标（has_any_data==False），保留活标。"""
        class PruneCatalog:
            def __init__(self, *a, **k): pass
            def has_any_data(self, ticker):
                return ticker in {"600519.SH", "000001.SZ"}
        monkeypatch.setattr(quote_callbacks, "_catalog", lambda: PruneCatalog())
        wl = ["600519.SH", "999999.SH", "000001.SZ", "888888.SH"]
        kept, removed = quote_callbacks._prune_watchlist(wl)
        assert kept == ["600519.SH", "000001.SZ"]
        assert set(removed) == {"999999.SH", "888888.SH"}

    def test_prune_watchlist_catalog_error_fail_open(self, monkeypatch):
        """FR-5.3 fail-open：目录不可读时不裁剪（kept==wl, removed==[]），避免误删。"""
        def _boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(quote_callbacks, "_catalog", _boom)
        wl = ["600519.SH", "999999.SH"]
        kept, removed = quote_callbacks._prune_watchlist(wl)
        assert kept == wl and removed == []

    def test_prune_watchlist_empty_input(self, monkeypatch):
        """空列表裁剪返回空，不报错。"""
        monkeypatch.setattr(quote_callbacks, "_catalog", lambda: None)
        kept, removed = quote_callbacks._prune_watchlist([])
        assert kept == [] and removed == []

    def test_update_watchlist_prunes_dead_symbols(self, monkeypatch, tmp_path):
        """FR-5.3 / T-4：刷新行情看板时清理 store 中死标并回写文件。"""
        import json
        from pathlib import Path
        wl_file = tmp_path / "watchlist.json"
        wl_file.write_text(json.dumps(["600519.SH", "999999.SH"], ensure_ascii=False),
                           encoding="utf-8")
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE", str(wl_file))
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB(quote_rows=[]))
        class PruneCatalog:
            def __init__(self, *a, **k): pass
            def has_any_data(self, ticker):
                return ticker == "600519.SH"
        monkeypatch.setattr(quote_callbacks, "CacheCatalogService",
                            lambda *a, **k: PruneCatalog())
        monkeypatch.setattr(quote_callbacks, "ctx", CtxStub(
            triggered=[{"prop_id": "qb-manual-refresh.n_clicks"}]))
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 1)
        watchlist, tbl = cb(None, 1, None, None, ["600519.SH", "999999.SH"], "none")
        assert watchlist == ["600519.SH"]
        assert isinstance(tbl, dash_table.DataTable)
        updated = json.loads(Path(wl_file).read_text(encoding="utf-8"))
        assert updated == ["600519.SH"]

    def test_prune_watchlist_on_load_ignores_other_pages(self, monkeypatch):
        """FR-5.3：非 /market-watch 路由不裁剪（no_update, no_update）。"""
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 7)
        assert cb("/data-center") == (no_update, no_update, no_update)

    def test_prune_watchlist_on_load_prunes_and_renders(self, monkeypatch, tmp_path):
        """FR-5.3 / T-4：导航到 /market-watch 即清理死标并渲染活标，且回写文件。"""
        import json
        from pathlib import Path
        wl_file = tmp_path / "watchlist.json"
        wl_file.write_text(json.dumps(["600519.SH", "999999.SH"], ensure_ascii=False),
                           encoding="utf-8")
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE", str(wl_file))
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB(quote_rows=[]))
        class PruneCatalog:
            def __init__(self, *a, **k): pass
            def has_any_data(self, ticker):
                return ticker == "600519.SH"
        monkeypatch.setattr(quote_callbacks, "CacheCatalogService",
                            lambda *a, **k: PruneCatalog())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 7)
        kept, tbl, chart = cb("/market-watch")
        assert kept == ["600519.SH"]
        assert chart == "600519.SH"
        assert isinstance(tbl, dash_table.DataTable)
        updated = json.loads(Path(wl_file).read_text(encoding="utf-8"))
        assert updated == ["600519.SH"]

    def test_prune_watchlist_on_load_empty_watchlist(self, monkeypatch, tmp_path):
        """FR-5.3：空自选导航到看板 → 空态文案，不报错。"""
        import json
        from pathlib import Path
        wl_file = tmp_path / "watchlist.json"
        wl_file.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(quote_callbacks, "QB_WATCHLIST_FILE", str(wl_file))
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 7)
        kept, tbl, chart = cb("/market-watch")
        assert kept == []
        assert chart is None
        assert "自选列表为空" in "".join(_text(tbl))


    def test_quote_row_adj_hfq_adjusts_price(self, monkeypatch):
        """Task #22：日线降级路径按后复权口径换算最新价与涨跌幅。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc

        class FakeDF:
            def __init__(self, cols):
                self._cols = cols
            def __len__(self):
                return len(next(iter(self._cols.values())))
            def __getitem__(self, key):
                return self._cols[key]

        class FakeDB:
            def query_df(self, sql, params=None):
                if "bars_daily" in sql:
                    return FakeDF({"close": [10.0, 9.0], "volume": [100, 90],
                                   "trade_date": ["2024-03-02", "2024-03-01"]})
                if "adj_factors" in sql:
                    date = (params or [None])[-1]
                    return FakeDF({"adj_factor": [2.0] if date == "2024-03-02" else [1.8]})
                return FakeDF({})

        monkeypatch.setattr(qc, "_get_db", lambda: FakeDB())
        row = qc._quote_row("600519.SH", None, None, adj_mode="hfq")
        assert row["last_price"] == "20.00"            # 10 * 2.0
        pct = float(row["change_pct"].strip("%"))
        assert abs(pct - (20.0 - 16.2) / 16.2 * 100) < 0.01  # 16.2 = 9 * 1.8

    def test_quote_row_adj_qfq_normalized_to_raw(self, monkeypatch):
        """Task #22：前复权最新日≈不复权价，涨跌幅与后复权一致（仅常数缩放差）。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc

        class FakeDF:
            def __init__(self, cols):
                self._cols = cols
            def __len__(self):
                return len(next(iter(self._cols.values())))
            def __getitem__(self, key):
                return self._cols[key]

        class FakeDB:
            def query_df(self, sql, params=None):
                if "bars_daily" in sql:
                    return FakeDF({"close": [10.0, 9.0], "volume": [100, 90],
                                   "trade_date": ["2024-03-02", "2024-03-01"]})
                if "adj_factors" in sql:
                    date = (params or [None])[-1]
                    return FakeDF({"adj_factor": [2.0] if date == "2024-03-02" else [1.8]})
                return FakeDF({})

        monkeypatch.setattr(qc, "_get_db", lambda: FakeDB())
        row = qc._quote_row("600519.SH", None, None, adj_mode="qfq")
        assert row["last_price"] == "10.00"            # 前复权最新日 = 原始收盘
        pct = float(row["change_pct"].strip("%"))
        assert abs(pct - 23.46) < 0.01

    def test_quote_row_adj_none_keeps_raw(self, monkeypatch):
        """Task #22：不复权口径下日线降级最新价=原始收盘价。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc

        class FakeDF:
            def __init__(self, cols):
                self._cols = cols
            def __len__(self):
                return len(next(iter(self._cols.values())))
            def __getitem__(self, key):
                return self._cols[key]

        class FakeDB:
            def query_df(self, sql, params=None):
                if "bars_daily" in sql:
                    return FakeDF({"close": [10.0, 9.0], "volume": [100, 90],
                                   "trade_date": ["2024-03-02", "2024-03-01"]})
                return FakeDF({})

        monkeypatch.setattr(qc, "_get_db", lambda: FakeDB())
        row = qc._quote_row("600519.SH", None, None, adj_mode="none")
        assert row["last_price"] == "10.00"
        pct = float(row["change_pct"].strip("%"))
        assert abs(pct - (10.0 - 9.0) / 9.0 * 100) < 0.01

    def test_quote_row_snapshot_unaffected_by_adj(self, monkeypatch):
        """Task #22：实时快照路径不受复权口径影响（实际成交价）。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc
        snap = {"last_price": 12.34, "pre_close": 12.0, "change_pct": 2.83,
                "volume": 500, "ts": "2024-03-02 10:00:00"}
        row = qc._quote_row("600519.SH", snap, None, adj_mode="hfq")
        assert row["last_price"] == "12.34"
        assert row["change_pct"] == "+2.83%"

    def test_coverage_badges_includes_financials(self):
        """Task #24：看板覆盖度徽标含第 5 类「财」，has_financials 决定绿/灰。"""
        import fisher.dash_app.callbacks.quote_callbacks as qc
        cov = {"has_daily": True, "has_minute": False, "has_realtime": True,
               "has_adj": False, "has_financials": True}
        md = qc._coverage_badges(cov)
        assert "财✓" in md and "财务数据" in md
        cov2 = dict(cov, has_financials=False)
        assert "财✗" in qc._coverage_badges(cov2)


def test_render_minute_chart_with_data(monkeypatch):
    """Task #25：看板分钟 K 线回调——按所选周期读取首个自选标的并产出 candlestick figure。"""
    import fisher.dash_app.callbacks.quote_callbacks as qc

    class _FakeDataSvc:
        def __init__(self):
            self.captured_period = None
        def get_minute_bars(self, ticker, period="5", limit=240):
            self.captured_period = period
            return [
                {"bar_time": "2024-01-02 09:35:00", "open": 100.0, "high": 101.0,
                 "low": 99.0, "close": 100.5, "volume": 1000},
                {"bar_time": "2024-01-02 09:36:00", "open": 100.5, "high": 102.0,
                 "low": 100.0, "close": 101.0, "volume": 1200},
            ]
    fake = _FakeDataSvc()
    monkeypatch.setattr(qc, "get_data_service", lambda: fake)

    with capture_dash_callbacks() as app:
        quote_callbacks.register_quote_callbacks(app)
        cb = app.get_callback("qb-minute-chart")
        fig = cb("5", "600519.SH")
    assert fake.captured_period == "5"
    # figure 为 plotly Figure：含 1 根 candlestick trace
    assert len(fig.data) == 1
    assert fig.data[0].type == "candlestick"


def test_render_minute_chart_empty_watchlist(monkeypatch):
    """Task #25：自选为空时返回带提示的空 figure，不抛错。"""
    import fisher.dash_app.callbacks.quote_callbacks as qc

    class _FakeDataSvc:
        def get_minute_bars(self, ticker, period="5", limit=240):
            return []
    monkeypatch.setattr(qc, "get_data_service", lambda: _FakeDataSvc())

    with capture_dash_callbacks() as app:
        quote_callbacks.register_quote_callbacks(app)
        cb = app.get_callback("qb-minute-chart")
        fig = cb("5", None)
    assert len(fig.data) == 0  # 无 K 线，仅提示 annotation


# =========================================================================== #
# 5) strategy_crud_callbacks
# =========================================================================== #
class TestStrategyCrudCallbacks:
    def test_registers(self):
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
        assert app.callback_count() >= 7
        assert callable(_nth(app, 0))
        assert callable(_nth(app, 4))   # handle_export

    def test_build_strategy_list_empty(self):
        el = strategy_crud_callbacks._build_strategy_list([])
        assert isinstance(el, html.Div)
        assert "暂无策略" in "".join(_text(el))

    def test_build_strategy_list_rows(self):
        strategies = [{
            "name": "s1", "type": "sma_cross", "symbols": ["600519"],
            "params": {"fast": 5, "slow": 20}, "enabled": True,
            "created_at": "2024-01-01 10:00:00",
        }]
        el = strategy_crud_callbacks._build_strategy_list(strategies)
        txt = "".join(_text(el))
        assert "s1" in txt and "均线交叉" in txt

    def test_build_strategy_list_dsl(self):
        strategies = [{
            "name": "dsl1", "type": "custom", "symbols": [],
            "params": {"dsl_config": {"a": 1}}, "enabled": True,
            "created_at": "2024-01-01 10:00:00",
        }]
        el = strategy_crud_callbacks._build_strategy_list(strategies)
        assert "DSL配置" in "".join(_text(el))

    def test_refresh_strategy_table(self, monkeypatch):
        strategies = [{"name": "s1", "type": "sma_cross", "symbols": [],
                       "params": {}, "enabled": True, "created_at": ""}]
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: FakeService(strategies={"s1": strategies[0]},
                                                list_strategies=strategies))
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 0)
        table, lst = cb("/strategy-center")
        assert isinstance(table, html.Div)
        assert lst == strategies

    def test_refresh_strategy_table_after_action(self, monkeypatch):
        strategies = [{"name": "s1", "type": "sma_cross", "symbols": [],
                       "params": {}, "enabled": True, "created_at": ""}]
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: FakeService(strategies={"s1": strategies[0]},
                                                list_strategies=strategies))
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 1)
        table, lst = cb("trigger", "/strategy-center")
        assert lst == strategies

    def test_handle_delete(self, monkeypatch):
        fake = FakeService(strategies={"s1": {"name": "s1"}})
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: fake)
        _patch_callback_context(monkeypatch, triggered=[{
            "prop_id": '{"type":"strategy-delete-btn","index":"s1"}.n_clicks',
            "value": 1}])
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 2)
        res = cb([1])
        assert isinstance(res, str)  # iso 时间戳
        assert ("delete_strategy", "s1") in fake.calls

    def test_handle_delete_no_trigger(self, monkeypatch):
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_callback_context(monkeypatch, triggered=[])
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 2)
        assert cb([None]) is no_update

    def test_handle_toggle(self, monkeypatch):
        fake = FakeService(strategies={"s1": {
            "name": "s1", "type": "sma_cross", "description": "",
            "params": {}, "symbols": [], "enabled": False}})
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: fake)
        _patch_callback_context(monkeypatch, triggered=[{
            "prop_id": '{"type":"strategy-toggle-switch","index":"s1"}.value',
            "value": True}])
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 3)
        res = cb([True])
        assert isinstance(res, str)
        assert ("save_strategy",) in [(c[0],) for c in fake.calls]
        saved = [c[1] for c in fake.calls if c[0] == "save_strategy"][0]
        assert saved.enabled is True

    def test_handle_export(self, monkeypatch):
        fake = FakeService(strategies={"s1": {"name": "s1"}},
                           export_json='{"name":"s1"}')
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: fake)
        _patch_callback_context(monkeypatch, triggered=[{
            "prop_id": '{"type":"strategy-export-btn","index":"s1"}.n_clicks',
            "value": 1}])
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 4)
        res = cb([1])
        assert isinstance(res, dict)
        assert res["filename"] == "s1.json"
        assert "s1" in res["content"]

    def test_handle_import_success(self, monkeypatch):
        payload = '{"name":"imp","type":"sma_cross","params":{}}'
        b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        contents = f"data:application/json;base64,{b64}"
        fake = FakeService(import_json={"status": "ok"})
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 5)
        trigger, toast = cb(contents, "imp.json")
        assert isinstance(trigger, str)
        assert "导入成功" in "".join(_text(toast))

    def test_handle_import_error(self, monkeypatch):
        payload = '{"name":"imp"}'
        b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        contents = f"data:application/json;base64,{b64}"
        fake = FakeService(import_json={"status": "error", "errors": ["缺 type"]})
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 5)
        trigger, toast = cb(contents, "imp.json")
        assert trigger is no_update
        assert "导入失败: 缺 type" in "".join(_text(toast))

    def test_handle_import_empty(self, monkeypatch):
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 5)
        trigger, toast = cb(None, None)
        assert trigger is no_update and toast == ""

    def test_trigger_import_file_dialog(self, monkeypatch):
        monkeypatch.setattr(strategy_crud_callbacks, "get_strategy_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            strategy_crud_callbacks.register_strategy_crud_callbacks(app)
            cb = _nth(app, 6)
        assert cb(1) is no_update


# =========================================================================== #
# 6) strategy_wizard_callbacks
# =========================================================================== #
@pytest.fixture
def _stub_wizard_steps(monkeypatch):
    for i in range(4):
        monkeypatch.setattr(strategy_wizard_callbacks,
                            f"_render_wizard_step_{i}",
                            lambda step=i, *a, **k: html.Div(f"STEP{step}"))


class TestStrategyWizardCallbacks:
    def test_registers(self):
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
        assert app.callback_count() >= 5
        assert callable(_nth(app, 0))

    def test_build_wizard_footer_steps(self):
        f0 = strategy_wizard_callbacks._build_wizard_footer(0)
        ids0 = [getattr(b, "id", None) for b in f0]
        assert "wizard-cancel-btn" in ids0 and "wizard-next-btn" in ids0
        assert "wizard-prev-btn" not in ids0
        f3 = strategy_wizard_callbacks._build_wizard_footer(3)
        ids3 = [getattr(b, "id", None) for b in f3]
        assert "wizard-save-btn" in ids3

    def test_get_wizard_title(self):
        assert strategy_wizard_callbacks._get_wizard_title(None) == "新建策略"
        assert strategy_wizard_callbacks._get_wizard_title("abc") == "编辑策略: abc"

    def test_add_error_to_footer(self):
        footer = [html.Div("btn")]
        out = strategy_wizard_callbacks._add_error_to_footer(footer, "boom")
        assert isinstance(out, list)
        assert "boom" in "".join(_text(out[0]))

    def test_collect_params_sma(self, monkeypatch):
        states = {"strategy-wizard-state.data": {
            "step": 1, "data": {"type": "sma_cross", "params": {"fast": 3, "slow": 9}}}}
        _patch_dash_ctx(monkeypatch, triggered=[], states=states)
        res = strategy_wizard_callbacks._collect_params_from_states()
        assert res == {"fast": 3, "slow": 9}

    def test_collect_params_custom(self, monkeypatch):
        states = {"strategy-wizard-state.data": {
            "step": 1, "data": {"type": "custom", "params": {"dsl_config": "{}"}}}}
        _patch_dash_ctx(monkeypatch, triggered=[], states=states)
        res = strategy_wizard_callbacks._collect_params_from_states()
        assert res == {"dsl_config": "{}"}

    def test_open_wizard_create(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "strategy-create-btn.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 0)
        is_open, body, footer, title, state, edit_id, confirm = cb(1, [])
        assert is_open is True
        assert title == "新建策略"
        assert state == {"step": 0, "data": {}}
        assert edit_id is None and confirm == ""

    def test_open_wizard_edit(self, monkeypatch, _stub_wizard_steps):
        fake = FakeService(strategies={"s1": {"name": "s1", "type": "sma_cross",
                                             "params": {}, "symbols": []}})
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: fake)
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[
            {"prop_id": '{"type":"strategy-edit-btn","index":"s1"}.n_clicks', "value": 1}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 0)
        is_open, body, footer, title, state, edit_id, confirm = cb(None, [1])
        assert is_open is True
        assert title == "编辑策略: s1"
        assert edit_id == "s1"

    def test_open_wizard_no_trigger(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, [])
        assert all(r is no_update for r in res)

    def test_navigation_cancel(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "wizard-cancel-btn.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 1)
        is_open, body, footer, title, state = cb(None, None, None, 1,
                                                 {"step": 2, "data": {}}, None,
                                                 None, None, None, None)
        assert is_open is False
        assert state == {"step": 0, "data": {}}

    def test_navigation_next_valid(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "wizard-next-btn.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 1)
        is_open, body, footer, title, state = cb(
            None, 1, None, None, {"step": 0, "data": {}}, None,
            "s1", "sma_cross", "desc", None)
        assert state["step"] == 1
        assert state["data"]["name"] == "s1"
        assert state["data"]["type"] == "sma_cross"

    def test_navigation_next_missing_name(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "wizard-next-btn.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 1)
        is_open, body, footer, title, state = cb(
            None, 1, None, None, {"step": 0, "data": {}}, None,
            "", "sma_cross", "desc", None)
        assert "请输入策略名称" in "".join(_text(footer))

    def test_navigation_save(self, monkeypatch, _stub_wizard_steps):
        fake = FakeService(strategies={"s1": {"name": "s1", "enabled": True}})
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: fake)
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "wizard-save-btn.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 1)
        is_open, body, footer, title, state = cb(
            None, None, 1, None,
            {"step": 3, "data": {"name": "s1", "type": "sma_cross",
                                 "params": {}, "symbols": []}},
            None, None, None, None, None)
        assert is_open is False
        assert ("save_strategy",) in [(c[0],) for c in fake.calls]

    def test_template_apply(self, monkeypatch, _stub_wizard_steps):
        fake = FakeService(list_strategies=[])
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: fake)
        _patch_dash_ctx(monkeypatch, triggered=[{"prop_id": "template-sma.n_clicks"}])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 2)
        res = cb(1, None, None, None, None)
        # 8 个输出：is_open, body, footer, title, state, edit_id, table, strategies
        assert len(res) == 8
        assert ("save_strategy",) in [(c[0],) for c in fake.calls]
        assert "暂无策略" in "".join(_text(res[6]))

    def test_load_symbol_pool_options(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService(cached_table=[
                                {"ticker": "600519", "market": "a_share",
                                 "records": 1, "start_date": "2024-01-01",
                                 "end_date": "2024-02-01"}]))
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 3)
        assert cb(False) == []
        assert cb(True) == [{"label": "600519", "value": "600519"}]

    def test_update_params_form_on_type_change(self, monkeypatch, _stub_wizard_steps):
        monkeypatch.setattr(strategy_wizard_callbacks, "get_strategy_service",
                            lambda: FakeService())
        _patch_dash_ctx(monkeypatch, triggered=[])
        with capture_dash_callbacks() as app:
            strategy_wizard_callbacks.register_strategy_wizard_callbacks(app)
            cb = _nth(app, 4)
        assert cb(None, {"step": 1, "data": {}}) is no_update
        res = cb("sma_cross", {"step": 1, "data": {}})
        assert "STEP" in "".join(_text(res))
        assert cb("sma_cross", {"step": 0, "data": {}}) is no_update
