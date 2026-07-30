"""行情看板页体验优化（PRD v1.1）单测：

- FR-1：分钟线午休区间隐藏（rangebreaks）
- FR-2：去缓存/批量补齐链接格式 + 数据中心 consume_cache_intent 预填待缓存池
- FR-3：日线自定义时间段（_fetch_daily_bars 区间过滤 + render_daily_chart 路由）
"""
import polars as pl
from unittest.mock import patch

from dash import no_update

from tests.helpers.dash_harness import capture_dash_callbacks


def _find_cb(app, name):
    """按函数名从捕获的回调列表中取回目标闭包（避免依赖注册顺序）。"""
    for cb in app.all_callbacks():
        if getattr(cb, "__name__", "") == name:
            return cb
    raise AssertionError(f"callback {name!r} not captured")


def test_minute_chart_hides_lunch_break():
    """FR-1：分钟图 X 轴应隐藏每日午休 11:30-13:00 空白带。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    bars = [
        {"bar_time": "2024-01-02 11:00:00", "open": 10, "high": 11, "low": 9, "close": 10.5},
        {"bar_time": "2024-01-02 11:30:00", "open": 10.5, "high": 10.8, "low": 10.2, "close": 10.6},
        {"bar_time": "2024-01-02 13:00:00", "open": 10.6, "high": 10.9, "low": 10.5, "close": 10.7},
        {"bar_time": "2024-01-02 15:00:00", "open": 10.7, "high": 10.9, "low": 10.6, "close": 10.8},
    ]
    fig = qc._build_minute_chart("600000.SH", "5", bars)
    rb = fig.layout.xaxis.rangebreaks
    assert rb is not None, "xaxis.rangebreaks 未设置"
    bounds = [d["bounds"] for d in rb]
    assert ("11:30", "13:00") in bounds


def test_minute_chart_empty_has_no_rangebreaks_error():
    """FR-1：无数据时仍应正常返回图（不抛错）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    fig = qc._build_minute_chart("600000.SH", "5", [])
    assert fig is not None


def test_goto_cache_link_format():
    """FR-2：行内「去补齐」链接应落获取数据页并携带 focus，且不再带无效的 tab=tab-cached。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    link = qc._goto_cache_link("600000.SH")
    assert link == "[去补齐](/data-center?focus=600000.SH&data_type=daily)"
    assert "tab=tab-cached" not in link


class _FakeDailyDB:
    """模拟 bars_daily 查询：支持自定义区间（BETWEEN）与固定档（DESC LIMIT）。"""

    def __init__(self, rows):
        self._rows = rows

    def query_df(self, sql, params=None):
        if ">=" in sql and "<=" in sql:
            s, e = params[1], params[2]
            filtered = [r for r in self._rows if s <= r["trade_date"] <= e]
            return pl.DataFrame(filtered, schema=self._schema())
        limit = params[1] if params and len(params) > 1 else 120
        # 模拟真实 SQL「ORDER BY trade_date DESC LIMIT ?」——最近 limit 条按降序返回，
        # 交由 _fetch_daily_bars 反转为升序。
        return pl.DataFrame(self._rows[-limit:][::-1], schema=self._schema())

    @staticmethod
    def _schema():
        return {
            "trade_date": pl.Utf8,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        }


def test_fetch_daily_bars_custom_range():
    """FR-3：自定义时间段应仅返回区间内日线，且升序。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    rows = [
        {"trade_date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"trade_date": "2024-03-05", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 200},
        {"trade_date": "2024-06-10", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 300},
        {"trade_date": "2024-12-01", "open": 12, "high": 14, "low": 11, "close": 13, "volume": 400},
    ]
    fake = _FakeDailyDB(rows)
    with patch.object(qc, "_get_db", lambda: fake):
        bars = qc._fetch_daily_bars("600000.SH", start="2024-02-01", end="2024-07-01")
    dates = [b["trade_date"] for b in bars]
    assert dates == ["2024-03-05", "2024-06-10"]
    assert dates == sorted(dates)  # 升序


def test_fetch_daily_bars_fixed_limit_unchanged():
    """FR-3：未给区间时保持原固定档 LIMIT 行为（非回归）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    rows = [
        {"trade_date": f"2024-01-{d:02d}", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}
        for d in range(1, 31)
    ]
    fake = _FakeDailyDB(rows)
    with patch.object(qc, "_get_db", lambda: fake):
        bars = qc._fetch_daily_bars("600000.SH", limit=5)
    # 固定档取最近 5 个交易日（DESC LIMIT 5 后反转为升序）
    assert len(bars) == 5
    assert [b["trade_date"] for b in bars] == sorted(b["trade_date"] for b in bars)


class _EmptyNameDB:
    def query_df(self, sql, params=None):
        return pl.DataFrame({"ticker": [], "name": []})


def test_consume_cache_intent_focus():
    """FR-2：单标的 focus 应预填待缓存池并激活获取数据 Tab。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _EmptyNameDB()):
        pool, hint = dcc.consume_cache_intent(
            "?focus=600000.SH", "/data-center", [])
    assert pool == [{"value": "600000.SH", "label": "600000.SH"}]
    assert "带入 1 个标的" in hint


def test_consume_cache_intent_symbols():
    """FR-2：批量 symbols（逗号拼接）应全部预填（上限 20）。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _EmptyNameDB()):
        pool, _ = dcc.consume_cache_intent(
            "?symbols=A.SH,B.SH,C.SH", "/data-center", [])
    assert [p["value"] for p in pool] == ["A.SH", "B.SH", "C.SH"]


def test_consume_cache_intent_merges_existing_pool():
    """FR-2：与现有待缓存池合并去重（按 value）。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _EmptyNameDB()):
        pool, _ = dcc.consume_cache_intent(
            "?focus=NEW.SH", "/data-center",
            [{"value": "OLD.SH", "label": "OLD"}])
    values = [p["value"] for p in pool]
    assert values == ["OLD.SH", "NEW.SH"]


def test_consume_cache_intent_ignores_cached_tab():
    """FR-2：tab=tab-cached 场景交由 consume_focus 处理，本回调不动作。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    res = dcc.consume_cache_intent("?focus=X.SH&tab=tab-cached", "/data-center", [])
    assert res == (no_update, no_update)


def test_consume_cache_intent_ignores_non_datacenter():
    """FR-2：非 /data-center 路径不动作。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    res = dcc.consume_cache_intent("?focus=X.SH", "/market-watch", [])
    assert res == (no_update, no_update)


# --------------------------------------------------------------------------- #
# FR-2：batch_goto_cache 回调（批量去缓存补齐——携带全部自选标的跳转）
# --------------------------------------------------------------------------- #
def test_batch_goto_cache_carries_symbols():
    """FR-2：看板有自选标的时，批量补齐按钮应跳转并携带 symbols 参数。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "batch_goto_cache")
        with patch.object(qc, "_load_watchlist", return_value=["600000.SH", "600519.SH"]):
            pathname, search = cb(1)
    assert pathname == "/data-center"
    assert search == "?symbols=600000.SH,600519.SH"


def test_batch_goto_cache_empty_watchlist_no_op():
    """FR-2：看板无自选标的时不应跳转（返回 no_update）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "batch_goto_cache")
        with patch.object(qc, "_load_watchlist", return_value=[]):
            res = cb(1)
    assert res == (no_update, no_update)


def test_batch_goto_cache_caps_at_20():
    """FR-2：自选超过 20 个时仅携带前 20 个，避免 URL 过长。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    wl = [f"{i:06d}.SH" for i in range(25)]
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "batch_goto_cache")
        with patch.object(qc, "_load_watchlist", return_value=wl):
            _, search = cb(1)
    carried = search[len("?symbols="):].split(",")
    assert len(carried) == 20


# --------------------------------------------------------------------------- #
# FR-3：render_daily_chart 回调路由（自定义时间段 vs 固定档）
# --------------------------------------------------------------------------- #
def test_render_daily_chart_custom_branch():
    """FR-3：选择「自定义」且起止日期齐全时，按区间过滤（传 start/end）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    captured = {}
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "render_daily_chart")
        with patch.object(qc, "_fetch_daily_bars", side_effect=lambda *a, **k: captured.update(k) or []), \
             patch.object(qc, "_build_daily_chart", return_value="FIG"):
            out = cb("600000.SH", "none", "custom", "2024-01-01", "2024-06-01")
    assert out == "FIG"
    assert captured.get("start") == "2024-01-01"
    assert captured.get("end") == "2024-06-01"
    assert "limit" not in captured


def test_render_daily_chart_fixed_branch():
    """FR-3：未选自定义时保持固定档 LIMIT（非回归）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    captured = {}
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "render_daily_chart")
        with patch.object(qc, "_fetch_daily_bars", side_effect=lambda *a, **k: captured.update(k) or []), \
             patch.object(qc, "_build_daily_chart", return_value="FIG"):
            cb("600000.SH", "none", 120, None, None)
    assert captured.get("limit") == 120
    assert "start" not in captured and "end" not in captured


def test_render_daily_chart_custom_without_dates_falls_back():
    """FR-3：选中自定义但日期未填时回退到固定档（避免空区间查询）。"""
    from fisher.dash_app.callbacks import quote_callbacks as qc
    captured = {}
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "render_daily_chart")
        with patch.object(qc, "_fetch_daily_bars", side_effect=lambda *a, **k: captured.update(k) or []), \
             patch.object(qc, "_build_daily_chart", return_value="FIG"):
            cb("600000.SH", "none", "custom", None, None)
    assert captured.get("limit") == 120


# --------------------------------------------------------------------------- #
# FR-2：consume_cache_intent 名称回填 / DB 失败兜底 / 20 上限
# --------------------------------------------------------------------------- #
class _NameDB:
    """symbol_dict 命中：返回标的名称。"""

    def query_df(self, sql, params=None):
        return pl.DataFrame({"ticker": params, "name": [f"{t}-名称" for t in params]})


class _RaiseDB:
    """symbol_dict 查询异常：consume_cache_intent 应静默兜底用 ticker 作 label。"""

    def query_df(self, sql, params=None):
        raise RuntimeError("db down")


def test_consume_cache_intent_name_lookup():
    """FR-2：symbol_dict 命中时预填 label 为名称（而非裸代码）。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _NameDB()):
        pool, _ = dcc.consume_cache_intent("?focus=600000.SH", "/data-center", [])
    assert pool == [{"value": "600000.SH", "label": "600000.SH-名称"}]


def test_consume_cache_intent_db_failure_fallback():
    """FR-2：symbol_dict 查询异常时静默兜底，label 回退为 ticker 本身。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _RaiseDB()):
        pool, _ = dcc.consume_cache_intent("?focus=600000.SH", "/data-center", [])
    assert pool == [{"value": "600000.SH", "label": "600000.SH"}]


def test_consume_cache_intent_symbols_cap_20():
    """FR-2：批量 symbols 超过 20 个时仅取前 20 个。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    with patch.object(dcc, "get_db", lambda: _EmptyNameDB()):
        pool, _ = dcc.consume_cache_intent(
            "?symbols=" + ",".join(f"S{i}.SH" for i in range(25)), "/data-center", [])
    assert len(pool) == 20


def test_consume_cache_intent_no_tickers_no_op():
    """FR-2：仅有 data_type 而无 focus/symbols 时不预填（返回 no_update）。"""
    from fisher.dash_app.callbacks import data_cache_callbacks as dcc
    res = dcc.consume_cache_intent("?data_type=daily", "/data-center", [])
    assert res == (no_update, no_update)


# --------------------------------------------------------------------------- #
# 「当日」快捷按钮（数据中心时间范围选择器）
# --------------------------------------------------------------------------- #
def test_set_range_today_sets_today():
    """数据中心获取时间范围「当日」按钮：start/end 都设为今天。"""
    from fisher.dash_app.callbacks import data_callbacks as dc
    from datetime import date
    with capture_dash_callbacks() as app:
        dc.register_data_callbacks(app)
        cb = _find_cb(app, "set_range_today")
        start, end = cb(1)
    today = date.today().isoformat()
    assert start == today and end == today


def test_set_export_today_sets_today():
    """数据中心导出起止日期「当日」按钮：两者都设为今天。"""
    from fisher.dash_app.callbacks import data_callbacks as dc
    from datetime import date
    with capture_dash_callbacks() as app:
        dc.register_data_callbacks(app)
        cb = _find_cb(app, "set_export_today")
        start, end = cb(1)
    today = date.today().isoformat()
    assert start == today and end == today


# --------------------------------------------------------------------------- #
# 「当日」快捷按钮（行情看板日线自定义时间段）
# --------------------------------------------------------------------------- #
def test_set_daily_today_start_sets_start_today_and_custom(monkeypatch):
    """日历弹窗内「当日」聚焦开始日期时：仅 start 设为今天，end 不变，并切到 custom。"""
    from types import SimpleNamespace
    from fisher.dash_app.callbacks import quote_callbacks as qc
    from datetime import date
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "set_daily_today")
        monkeypatch.setattr(qc, "ctx", SimpleNamespace(triggered_id="qb-daily-today-start-btn"))
        start, end, mode = cb(1, None, "2024-01-01", "2024-01-10")
    today = date.today().isoformat()
    assert start == today
    assert end is no_update
    assert mode == "custom"


def test_set_daily_today_end_sets_end_today_and_custom(monkeypatch):
    """日历弹窗内「当日」聚焦结束日期时：仅 end 设为今天，start 不变，并切到 custom。"""
    from types import SimpleNamespace
    from fisher.dash_app.callbacks import quote_callbacks as qc
    from datetime import date
    with capture_dash_callbacks() as app:
        qc.register_quote_callbacks(app)
        cb = _find_cb(app, "set_daily_today")
        monkeypatch.setattr(qc, "ctx", SimpleNamespace(triggered_id="qb-daily-today-end-btn"))
        start, end, mode = cb(None, 1, "2024-01-01", "2024-01-10")
    today = date.today().isoformat()
    assert start is no_update
    assert end == today
    assert mode == "custom"


