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


def _run_generator(gen):
    """消费 background 回调生成器，返回其最终的 return 值（StopIteration.value）。"""
    final = None
    try:
        while True:
            next(gen)
    except StopIteration as e:
        final = e.value
    return final


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
    def test_registers(self):
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
        assert app.callback_count() >= 6
        assert callable(_nth(app, 0))   # search_symbols
        assert callable(_nth(app, 1))   # fetch_data

    def test_search_symbols_too_short(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 0)
        # V1.2：回调现返回 4 元组（新增 search-results-store 数据），状态为组件
        opts, val, status, store = cb("a")
        assert opts == [] and val is None and store == []
        assert "至少" in "".join(_text(status))

    def test_search_symbols_matches(self, monkeypatch):
        fake = FakeService(search_symbols=[
            {"label": "600519 贵州茅台", "value": "600519.SH", "market": "a_share"}])
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 0)
        opts, val, status, store = cb("6005")
        assert opts == [{"label": "600519 贵州茅台", "value": "600519.SH"}]
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
            cb = _nth(app, 0)
        opts, val, status, store = cb("600519")
        # R-31：不再暴露技术堆栈，改为友好文案
        assert opts == [] and store == []
        assert "暂时不可用" in "".join(_text(status))

    def test_fetch_data_no_symbols(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 1)
        final = _run_generator(cb(1, None, "", "2024-01-01", "2024-02-01", "daily", ""))
        assert final[0] == "请先选择或输入标的"
        assert final[1] == "请先搜索并选择标的"

    def test_fetch_data_success(self, monkeypatch):
        fake = FakeService(fetch_bars={"600519": {"status": "ok", "count": 5}})
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 1)
        final = _run_generator(
            cb(1, "600519", "", "2024-01-01", "2024-02-01", "daily", ""))
        assert isinstance(final[0], html.Div)
        assert isinstance(final[1], html.Div)
        assert "✓ 600519: 5条记录" in "".join(_text(final[0]))
        assert final[2]["current"] == final[2]["total"] == 1
        assert ("fetch_bars", ["600519"]) in fake.calls

    def test_fetch_data_batch_input(self, monkeypatch):
        fake = FakeService(fetch_bars={
            "600519": {"status": "ok", "count": 2},
            "000001": {"status": "ok", "count": 3},
        })
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 1)
        final = _run_generator(
            cb(1, None, "600519, 000001\n", "2024-01-01", "2024-02-01", "daily", ""))
        assert final[2]["total"] == 2
        assert "✓ 600519: 2条记录" in "".join(_text(final[0]))

    def test_update_fetch_list(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 2)
        # V1.2：选中回调现接收 (selected, search-results-store)
        none_case = cb(None, [])
        assert none_case == "请先搜索并选择标的"
        results = [{"value": "600519.SH", "code": "600519", "name": "贵州茅台",
                    "market": "a_share", "pinyin_abbr": "GZMT"}]
        sel_case = cb("600519.SH", results)
        txt = "".join(_text(sel_case))
        assert "贵州茅台" in txt and "600519" in txt

    def test_clear_single_search_on_batch(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 3)
        assert cb("600519") is None          # 有批量输入 -> 清空单选
        assert cb("") is no_update           # 无批量输入 -> 保持不变

    def test_toggle_minute_period(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 4)
        assert cb("minute") == {"display": "block"}
        assert cb("daily") == {"display": "none"}

    def test_close_modal(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
            cb = _nth(app, 5)
        assert cb(1) is False


# =========================================================================== #
# 2) data_cache_callbacks
# =========================================================================== #
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

    def test_force_refresh_cached_not_active(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 0)
        assert cb(1, "tab-other") is no_update

    def test_force_refresh_cached_with_rows(self, monkeypatch):
        rows = [{"ticker": "000001", "market": "a_share", "records": 5,
                 "start_date": "2024-01-01", "end_date": "2024-02-01"}]
        fake = FakeService(cached_table=rows)
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 0)
        res = cb(1, "tab-cached")
        assert isinstance(res, dash_table.DataTable)
        assert res.id == "cached-data-table"
        assert res.data == rows

    def test_render_cached_table_not_active(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService())
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        assert cb("tab-live", "all", "", 0, 0, 0, None) is no_update

    def test_render_cached_table_with_rows(self, monkeypatch):
        rows = [{"ticker": "600519", "market": "a_share", "records": 10,
                 "start_date": "2024-01-01", "end_date": "2024-02-01"}]
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=rows))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        res = cb("tab-cached", "all", "", 1, 1, 0, None)
        assert isinstance(res, dash_table.DataTable)
        assert res.id == "cached-data-table"
        assert res.data == rows

    def test_render_cached_table_empty(self, monkeypatch):
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=[]))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        res = cb("tab-cached", "all", "", 1, 1, 0, None)
        assert isinstance(res, html.Div)
        assert "暂无缓存数据" in "".join(_text(res))

    def test_render_cached_table_poll_preserves_pagination(self, monkeypatch):
        """回归测试：auto-load 轮询(3s)触发回调时，若缓存数据未变化必须 no_update，
        否则 DataTable 的 page_current 会被重置回第 1 页（用户翻页后自动跳回的 bug）。"""
        rows = [
            {"ticker": "600519", "market": "a_share", "records": 10,
             "start_date": "2024-01-01", "end_date": "2024-02-01"},
            {"ticker": "000001", "market": "a_share", "records": 8,
             "start_date": "2024-01-01", "end_date": "2024-02-01"},
        ]
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=rows))
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 1)
        # 首次渲染（current_data=None）必须构建表格
        first = cb("tab-cached", "all", "", 1, 1, 0, None)
        assert isinstance(first, dash_table.DataTable)
        # 模拟一次轮询 tick：数据相同（current_data 即上一次返回的 data）
        # —— 关键断言：必须 no_update，否则翻页状态被重置
        again = cb("tab-cached", "all", "", 1, 1, 1, first.data)
        assert again is no_update
        # 数据真正变化时必须重建（保证自动加载新增标的仍会刷新）
        changed = [dict(rows[0]), {"ticker": "300750", "market": "a_share",
                                   "records": 3, "start_date": "2024-03-01",
                                   "end_date": "2024-04-01"}]
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=changed))
        rebuilt = cb("tab-cached", "all", "", 1, 1, 2, rows)  # current_data=旧 2 行
        assert isinstance(rebuilt, dash_table.DataTable)
        assert any(r["ticker"] == "300750" for r in rebuilt.data)
        # 日期类型差异不应误判为变化（DB 返回 date / DataTable 回传 str）
        date_obj_rows = [dict(r, start_date=_dtmod.date(2024, 1, 1),
                              end_date=_dtmod.date(2024, 2, 1)) for r in rows]
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: FakeService(cached_table=date_obj_rows))
        with_dates = cb("tab-cached", "all", "", 1, 1, 3, first.data)
        assert with_dates is no_update

    def test_delete_selected_rows(self, monkeypatch):
        rows = [{"ticker": "600519", "market": "a_share", "records": 1,
                 "start_date": "2024-01-01", "end_date": "2024-02-01"}]
        fake = FakeService(cached_table=rows)
        monkeypatch.setattr(data_cache_callbacks, "get_data_service",
                            lambda: fake)
        with capture_dash_callbacks() as app:
            data_cache_callbacks.register_data_cache_callbacks(app)
            cb = _nth(app, 2)
        assert cb(1, None, None) is no_update
        res = cb(1, [0], [{"ticker": "600519"}, {"ticker": "000001"}])
        assert isinstance(res, dash_table.DataTable)
        assert ("delete_symbols", ["600519"]) in fake.calls


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

    def test_load_qb_symbols(self, monkeypatch):
        db = FakeDuckDB(distinct_rows={"ticker": ["600519", "000001"]})
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: db)
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 0)
        res = cb("/quote-board")
        assert res == [{"label": "600519", "value": "600519"},
                       {"label": "000001", "value": "000001"}]

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
        watchlist, tbl = cb(1, None, None, "600519.SZ", None)
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
        watchlist, tbl = cb(None, 1, None, None, None)
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
        assert cb("/quote-board") is True

    def test_check_trading_hours_lunch_closed(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 3, 12, 30, 0))  # 周三午休（修复前误判为开市）
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/quote-board") is False

    def test_check_trading_hours_weekend_closed(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 6, 10, 0, 0))  # 周六
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/quote-board") is False

    def test_check_trading_hours_after_close(self, monkeypatch):
        monkeypatch.setattr(quote_callbacks, "DuckDBManager",
                            lambda *a, **k: FakeDuckDB())
        _patch_now(monkeypatch, (2024, 1, 3, 16, 0, 0))  # 收盘后
        with capture_dash_callbacks() as app:
            quote_callbacks.register_quote_callbacks(app)
            cb = _nth(app, 3)
        assert cb("/quote-board") is False


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
