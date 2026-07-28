"""T-UAT：标的搜索功能优化 V1.2 用户验收测试（11 例）。

逐条对应 PRD 第 9 节《验收标准（UAT）》。UI 层视觉细节（徽章颜色、高亮片段）在
回调/服务层以「命中 + 结构化字段 + 文案」的可验证形式断言；纯视觉样式不在自动化范围内，
以数据契约保证（market/徽章类型、拼音标签字段、状态区文案）。

隔离：akshare 全部 mock（refresh 用真 pandas.DataFrame）；DB 用 conftest in_memory_db。
"""
import time

import pandas as pd
import pytest

from fisher.dash_app.services.data_center_service import DataCenterService
from tests.helpers.dash_harness import capture_dash_callbacks
from fisher.dash_app.callbacks import data_callbacks


# --------------------------------------------------------------------------- #
# 全量字典种子：A股（含贵州茅台/招商银行）+ 港股通（含腾讯控股），另留一只非港股通港股用于范围核对
# --------------------------------------------------------------------------- #
_A_SHARE = [
    ("600519", "贵州茅台", "GUIZHOUMAOTAI", "GZMT"),
    ("600036", "招商银行", "ZHAOSHANGYINHANG", "ZSYH"),
    ("600000", "浦发银行", "PUFAYINHANG", "PFYH"),
    ("600004", "白云机场", "BAIYUNJICHANG", "BYJC"),
]
_HK_CONNECT = [
    ("00700", "腾讯控股", "TENGXUNKONGGU", "TXKG"),
    ("00941", "中国移动", "ZHONGGUOYIDONG", "ZGYD"),
]
# 抽样：以下港股「非港股通」，字典中不应存在（范围核对用）
_NON_GGT_HK = ["08000", "01234", "02888"]


@pytest.fixture
def uat_service(in_memory_db, limiter):
    rows = []
    for code, name, pf, pa in _A_SHARE:
        rows.append([f"{code}.SH", code, name, "a_share", pf, pa])
    for code, name, pf, pa in _HK_CONNECT:
        rows.append([f"{code}.HK", code, name, "hk_connect", pf, pa])
    in_memory_db.execute_many(
        "INSERT INTO symbol_dict (ticker, code, name, market, pinyin_full, pinyin_abbr) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    svc = DataCenterService(in_memory_db, limiter)
    svc._legacy_search = False
    return svc


def _search_cb_with(svc, monkeypatch):
    """捕获 search_symbols 回调并注入指定服务（by_output 取回调，无顺序依赖）。"""
    monkeypatch.setattr("fisher.dash_app.services.get_data_service", lambda: svc)
    with capture_dash_callbacks() as app:
        data_callbacks.register_data_callbacks(app)
    return app.by_output("search-status"), app.by_output("selected-pool")


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


# UAT-1：gzmt → 含 600519 贵州茅台，排前列（拼音首字母）
def test_uat_01_pinyin_abbr(uat_service):
    res = uat_service.search_symbols("gzmt")
    assert res, "拼音首字母应命中"
    codes = [r["code"] for r in res]
    assert "600519" in codes
    assert codes[0] == "600519"  # 排前列


# UAT-2：茅台 → 命中贵州茅台（高亮由 UI，此处验证命中 + 名称）
def test_uat_02_name_substring(uat_service):
    res = uat_service.search_symbols("茅台")
    assert any(r["name"] == "贵州茅台" for r in res)


# UAT-3：600 → 代码前缀 600 的 A股，响应 ≤ 300ms
def test_uat_03_code_prefix_latency(uat_service):
    t0 = time.perf_counter()
    res = uat_service.search_symbols("600")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert res
    assert all(r["code"].startswith("600") for r in res)
    assert all(r["market"] == "a_share" for r in res)
    assert elapsed_ms <= 300, f"响应 {elapsed_ms:.1f}ms 超过 300ms"


# UAT-4：腾讯 / 700 / 00700 → 命中 00700.HK 腾讯控股，HK 徽章，属港股通
@pytest.mark.parametrize("q", ["腾讯", "700", "00700"])
def test_uat_04_hk_connect_hit(uat_service, q):
    res = uat_service.search_symbols(q)
    hit = next((r for r in res if r["value"] == "00700.HK"), None)
    assert hit is not None, f"输入 {q!r} 应命中 00700.HK"
    assert hit["name"] == "腾讯控股"
    assert hit["market"] == "hk_connect"          # 港股徽章数据契约
    assert "港股" in hit["label"]


# UAT-5：minimax（非上市）→ 空结果 + 引导文案，无报错/无静默丢结果
def test_uat_05_no_match_guidance(uat_service, monkeypatch):
    search_cb, _ = _search_cb_with(uat_service, monkeypatch)
    opts, status, store = search_cb("minimax")
    assert opts == [] and store == []
    txt = _text(status)
    assert "未找到" in txt  # 友好引导，而非静默/报错


# UAT-6：%'-- → 无报错，按字面量搜索返回空结果引导（R-22 转义）
def test_uat_06_sql_special_chars(uat_service, monkeypatch):
    search_cb, _ = _search_cb_with(uat_service, monkeypatch)
    # 不应抛异常（%'-- 无空白/逗号，走单 token 链路）
    opts, status, store = search_cb("%'--")
    assert opts == []           # 字面量匹配无命中
    assert "未找到" in _text(status)


# UAT-7：断网后搜索 → 使用本地字典正常返回
def test_uat_07_offline_uses_local_dict(uat_service, monkeypatch):
    import akshare as ak

    def _down(*a, **k):
        raise ConnectionError("network down")

    for fn in ("stock_info_a_code_name", "stock_hk_spot",
               "stock_hk_ggt_components_em"):
        monkeypatch.setattr(ak, fn, _down, raising=False)
    res = uat_service.search_symbols("600519")
    assert any(r["code"] == "600519" for r in res)


# UAT-8：缓存页名称列 + 按"招商"过滤出 600036
def test_uat_08_cached_name_and_filter(uat_service):
    uat_service._db.execute(
        "INSERT INTO bars_daily VALUES "
        "('600036.SH','2024-01-02',30,31,29,30.5,1e6,3e7,'a_share',1.0)")
    rows = uat_service.get_cached_table()
    assert rows[0]["name"] == "招商银行"
    filtered = uat_service.get_cached_table(text_filter="招商")
    assert len(filtered) == 1 and filtered[0]["ticker"] == "600036.SH"


# UAT-9：缓存中存在字典无名 ticker → 名称显示"—"，可选可删
def test_uat_09_missing_name_placeholder(uat_service):
    uat_service._db.execute(
        "INSERT INTO bars_daily VALUES "
        "('900999.SH','2024-01-02',1,1,1,1,1,1,'a_share',1.0)")  # 字典中无此 ticker
    rows = uat_service.get_cached_table(text_filter="900999")
    assert len(rows) == 1
    assert rows[0]["name"] == "—"                # FR-4.2 占位
    # 可删
    assert uat_service.delete_symbols(["900999.SH"]) == 1


# UAT-10：字典刷新 —— 批量写入成功、港股来源为 stock_hk_spot（与自动加载宇宙同源自洽）、耗时达标
def test_uat_10_refresh_source_and_budget(in_memory_db, limiter, monkeypatch):
    import akshare as ak
    called = {"ggt": False, "spot": False}

    def _a():
        return pd.DataFrame([("600519", "贵州茅台")], columns=["code", "name"])

    def _ggt():
        called["ggt"] = True
        return pd.DataFrame([{"序号": 1, "代码": "00700", "名称": "腾讯控股"}])

    def _spot(*a, **k):
        called["spot"] = True
        return pd.DataFrame([{"代码": "00700", "中文名称": "腾讯控股"}])

    monkeypatch.setattr(ak, "stock_info_a_code_name", _a, raising=False)
    monkeypatch.setattr(ak, "stock_hk_ggt_components_em", _ggt, raising=False)
    monkeypatch.setattr(ak, "stock_hk_spot", _spot, raising=False)

    svc = DataCenterService(in_memory_db, limiter)
    stat = svc.refresh_symbol_dict()
    assert stat["replaced"] is True and stat["total"] == 2
    assert called["spot"] is True         # 港股来源为全量快照 stock_hk_spot
    assert called["ggt"] is False         # 不再依赖易失败的港股通成分接口
    assert stat["elapsed_ms"] < 3000      # PRD FR-2.3 ≤ 3s（小样本远低于）


# UAT-11：港股范围核对 —— 字典覆盖全部港股（含非港股通），均可搜到
def test_uat_11_hk_scope_all_market(in_memory_db, limiter, monkeypatch):
    import akshare as ak

    def _a():
        return pd.DataFrame([("600519", "贵州茅台")], columns=["code", "name"])

    def _spot(*a, **k):
        # 同时含港股通成分（00941）与非港股通港股（08000），验证全港股覆盖
        return pd.DataFrame([
            {"代码": "00941", "中文名称": "中国移动"},
            {"代码": "08000", "中文名称": "非港股通港股"},
        ])

    monkeypatch.setattr(ak, "stock_info_a_code_name", _a, raising=False)
    monkeypatch.setattr(ak, "stock_hk_spot", _spot, raising=False)
    svc = DataCenterService(in_memory_db, limiter)
    svc.refresh_symbol_dict()
    # 港股通成分可搜到
    assert svc.search_symbols("00941")
    # 非港股通港股也覆盖在字典中，可搜到
    assert any(r["value"] == "08000.HK" for r in svc.search_symbols("08000"))
