"""T-IT：标的搜索功能优化 V1.2 集成测试（5+ 例）。

覆盖跨层的端到端链路，而非单个纯函数：
  1. refresh_symbol_dict（真库原子写入）→ search_symbols（只读命中）全链路；
  2. 港股通零填充变体检索（"700" → 00700 腾讯控股）；
  3. 搜索回调 → search-results-store → 选中回填 update_fetch_list 富卡片（双回调 + 真服务 + 真库）；
  4. 原子替换：二次刷新用新数据整体替换旧字典；
  5. 空数据源保护：二次刷新数据源为空时保留旧字典不清空；
  6. R-50 legacy 回滚：legacy=true 时走旧 symbol_cache/实时链路，输出旧标签格式；
  7. R-33 缓存表：抓取后 LEFT JOIN 字典带出名称列。

隔离策略：akshare 一律 mock（refresh 用真 pandas.DataFrame，因服务用 df[[...]].itertuples）；
DB 用 conftest 的 in_memory_db（真 DuckDB 内存库）。禁止真实网络。
"""
import pandas as pd
import pytest

from fisher.dash_app.services.data_center_service import DataCenterService
from tests.helpers.dash_harness import capture_dash_callbacks
from fisher.dash_app.callbacks import data_callbacks


# --------------------------------------------------------------------------- #
# akshare 数据源 mock（真 pandas.DataFrame，供 refresh_symbol_dict.itertuples 使用）
# --------------------------------------------------------------------------- #
def _mock_sources(monkeypatch, a_rows, hk_rows):
    import akshare as ak

    def _a():
        return pd.DataFrame(a_rows, columns=["code", "name"])

    def _hk():
        return pd.DataFrame(
            [{"代码": c, "中文名称": n} for c, n in hk_rows]
        )

    monkeypatch.setattr(ak, "stock_info_a_code_name", _a, raising=False)
    monkeypatch.setattr(ak, "stock_hk_spot", _hk, raising=False)


@pytest.fixture
def svc_new(in_memory_db, limiter):
    """强制走新只读链路的服务（legacy=False），基于真 DuckDB 内存库。"""
    s = DataCenterService(in_memory_db, limiter)
    s._legacy_search = False
    return s


# --------------------------------------------------------------------------- #
# 1. refresh → search 全链路
# --------------------------------------------------------------------------- #
def test_refresh_then_search_a_share(svc_new, monkeypatch):
    _mock_sources(
        monkeypatch,
        a_rows=[("600519", "贵州茅台"), ("000001", "平安银行")],
        hk_rows=[("00700", "腾讯控股")],
    )
    stat = svc_new.refresh_symbol_dict()
    assert stat["replaced"] is True
    assert stat["a_share"] == 2 and stat["hk_connect"] == 1 and stat["total"] == 3

    # 代码检索命中，且 refresh 后 search 不再触发任何实时 akshare 调用
    import akshare as ak
    monkeypatch.setattr(ak, "stock_info_a_code_name",
                        lambda: (_ for _ in ()).throw(AssertionError("search 不应触网")),
                        raising=False)
    res = svc_new.search_symbols("600519")
    assert len(res) == 1
    assert res[0]["value"] == "600519.SH"
    assert res[0]["name"] == "贵州茅台"
    assert res[0]["market"] == "a_share"

    # 名称检索命中
    by_name = svc_new.search_symbols("平安")
    assert any(r["code"] == "000001" for r in by_name)


def test_refresh_then_search_hk_zero_pad(svc_new, monkeypatch):
    _mock_sources(
        monkeypatch,
        a_rows=[("600519", "贵州茅台")],
        hk_rows=[("00700", "腾讯控股"), ("00941", "中国移动")],
    )
    svc_new.refresh_symbol_dict()
    # 用户输入 3 位 "700"，R-21 零填充变体 → 命中 00700
    res = svc_new.search_symbols("700")
    tickers = {r["value"] for r in res}
    assert "00700.HK" in tickers
    hit = next(r for r in res if r["value"] == "00700.HK")
    assert hit["market"] == "hk_connect"
    assert hit["name"] == "腾讯控股"


# --------------------------------------------------------------------------- #
# 3. 搜索回调 → store → 选中回填富卡片（双回调链路）
# --------------------------------------------------------------------------- #
def test_search_store_to_fetch_list_card(svc_new, monkeypatch):
    _mock_sources(
        monkeypatch,
        a_rows=[("600519", "贵州茅台")],
        hk_rows=[("00700", "腾讯控股")],
    )
    svc_new.refresh_symbol_dict()
    monkeypatch.setattr("fisher.dash_app.services.get_data_service", lambda: svc_new)

    with capture_dash_callbacks() as app:
        data_callbacks.register_data_callbacks(app)
        cbs = app.all_callbacks()
    search_cb = cbs[0]          # search_symbols
    update_fetch_cb = cbs[2]    # update_fetch_list（第 3 个注册）

    opts, val, status, store = search_cb("600519")
    assert opts and opts[0]["value"] == "600519.SH"
    assert store and store[0]["name"] == "贵州茅台"

    # 用 store 数据回填选中卡片
    card = update_fetch_cb("600519.SH", store)

    def _flatten(node):
        out = []
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, (list, tuple)):
            for c in node:
                out.extend(_flatten(c))
        elif hasattr(node, "children"):
            out.extend(_flatten(node.children))
        return out

    text = "".join(_flatten(card))
    assert "贵州茅台" in text
    assert "600519" in text
    assert "600519.SH" in text  # 标准代码


# --------------------------------------------------------------------------- #
# 4. 原子替换：二次刷新整体替换旧字典
# --------------------------------------------------------------------------- #
def test_refresh_atomic_replace(svc_new, monkeypatch):
    _mock_sources(monkeypatch, a_rows=[("600519", "贵州茅台")], hk_rows=[])
    svc_new.refresh_symbol_dict()
    assert svc_new.search_symbols("600519")

    # 第二次刷新换成完全不同的清单
    _mock_sources(monkeypatch, a_rows=[("000001", "平安银行")], hk_rows=[])
    stat = svc_new.refresh_symbol_dict()
    assert stat["replaced"] is True
    assert svc_new.search_symbols("600519") == []       # 旧标的被清除
    assert svc_new.search_symbols("000001")             # 新标的存在


# --------------------------------------------------------------------------- #
# 5. 空数据源保护：保留旧字典
# --------------------------------------------------------------------------- #
def test_refresh_empty_sources_keeps_old(svc_new, monkeypatch):
    _mock_sources(monkeypatch, a_rows=[("600519", "贵州茅台")], hk_rows=[])
    svc_new.refresh_symbol_dict()

    # 两个数据源都抛异常 → rows 为空 → 不替换
    import akshare as ak

    def _boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(ak, "stock_info_a_code_name", _boom, raising=False)
    monkeypatch.setattr(ak, "stock_hk_spot", _boom, raising=False)
    stat = svc_new.refresh_symbol_dict()
    assert stat["replaced"] is False
    assert svc_new.search_symbols("600519")             # 旧字典仍在


# --------------------------------------------------------------------------- #
# 6. R-50 legacy 回滚链路
# --------------------------------------------------------------------------- #
def test_legacy_rollback_uses_old_path(in_memory_db, limiter, monkeypatch):
    # 准备旧 symbol_cache 表 + 数据
    in_memory_db.execute(
        "CREATE TABLE IF NOT EXISTS symbol_cache (code VARCHAR PRIMARY KEY, name VARCHAR)")
    in_memory_db.execute("INSERT INTO symbol_cache VALUES ('600519','贵州茅台')")

    import akshare as ak
    monkeypatch.setattr(ak, "stock_hk_spot",
                        lambda: pd.DataFrame(columns=["代码", "名称"]), raising=False)

    svc = DataCenterService(in_memory_db, limiter)
    svc._legacy_search = True   # 显式回滚
    res = svc.search_symbols("600519")
    # 旧链路标签格式："600519 - 贵州茅台"
    assert any("600519 - 贵州茅台" == r["label"] for r in res)


# --------------------------------------------------------------------------- #
# 8. R-02 冷启动状态机：字典为空 => "初始化中"；字典非空且无匹配 => "未找到"
# --------------------------------------------------------------------------- #
def _text(node):
    out = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, (list, tuple)):
        for c in node:
            out.extend(_text(c))
    elif hasattr(node, "children"):
        out.extend(_text(node.children))
    return "".join(out)


def test_cold_start_shows_initializing_when_dict_empty(svc_new, monkeypatch):
    # 字典为空（冷启动中），未做 refresh
    assert svc_new.symbol_dict_ready() is False
    monkeypatch.setattr("fisher.dash_app.services.get_data_service", lambda: svc_new)
    with capture_dash_callbacks() as app:
        data_callbacks.register_data_callbacks(app)
        search_cb = app.all_callbacks()[0]
    opts, val, status, store = search_cb("600519")
    assert opts == [] and store == []
    assert "初始化中" in _text(status)


def test_ready_dict_no_match_shows_not_found(svc_new, monkeypatch):
    _mock_sources(monkeypatch, a_rows=[("600519", "贵州茅台")], hk_rows=[])
    svc_new.refresh_symbol_dict()
    assert svc_new.symbol_dict_ready() is True
    monkeypatch.setattr("fisher.dash_app.services.get_data_service", lambda: svc_new)
    with capture_dash_callbacks() as app:
        data_callbacks.register_data_callbacks(app)
        search_cb = app.all_callbacks()[0]
    opts, val, status, store = search_cb("zzzzzz")
    assert opts == []
    assert "未找到" in _text(status)


# --------------------------------------------------------------------------- #
# 7. R-33 缓存表 LEFT JOIN 名称列
# --------------------------------------------------------------------------- #
def test_cached_table_shows_name_after_fetch(svc_new, monkeypatch):
    _mock_sources(monkeypatch, a_rows=[("600519", "贵州茅台")], hk_rows=[])
    svc_new.refresh_symbol_dict()

    # 直接写入一条日线，模拟已抓取
    svc_new._db.execute(
        "INSERT INTO bars_daily VALUES "
        "('600519.SH','2024-01-02',100,101,99,100.5,1000000,1.005e8,'a_share',1.0)")
    rows = svc_new.get_cached_table()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "600519.SH"
    assert rows[0]["name"] == "贵州茅台"

    # 按名称过滤
    filtered = svc_new.get_cached_table(text_filter="茅台")
    assert len(filtered) == 1
