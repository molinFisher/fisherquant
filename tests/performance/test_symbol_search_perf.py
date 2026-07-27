"""T-PERF：标的搜索 V1.2 性能与回归核对。

PRD 关键性能诉求：搜索走只读字典、单次查询应在毫秒级返回，且结果被截断到 MAX_RESULTS；
刷新为后台任务，需能在合理时间内完成全量写入。这里用「全量规模」的字典（~6000 条）做
基准，阈值取宽松值以避免 CI 抖动，重点在于：
  - 搜索 P95 延迟远低于交互阈值；
  - 单次查询永不超过 MAX_RESULTS 条；
  - 搜索链路零实时 akshare 调用（回归护栏）；
  - 全量刷新（DELETE + 批量 INSERT 原子替换）在阈值内完成。
"""
import time

import pandas as pd
import pytest

from fisher.dash_app.services.data_center_service import DataCenterService
from fisher.dash_app.services.symbol_search import MAX_RESULTS


N_A = 5500
N_HK = 600


def _percentile(values, pct):
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


@pytest.fixture
def big_dict_service(in_memory_db, limiter):
    """灌入 ~6100 条标的的服务（真 DuckDB 内存库），强制新只读链路。"""
    rows = []
    for i in range(N_A):
        code = f"{600000 + i:06d}"
        rows.append([f"{code}.SH", code, f"沪市公司{i}", "a_share", f"GS{i}", f"G{i % 100}"])
    for i in range(N_HK):
        code = f"{i:05d}"
        rows.append([f"{code}.HK", code, f"港股公司{i}", "hk_connect", f"HK{i}", f"H{i % 100}"])
    in_memory_db.execute_many(
        "INSERT INTO symbol_dict (ticker, code, name, market, pinyin_full, pinyin_abbr) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    svc = DataCenterService(in_memory_db, limiter)
    svc._legacy_search = False
    return svc


def test_search_latency_p95(big_dict_service):
    queries = ["600", "6005", "600123", "沪市", "GS10", "港股", "00700", "700", "G50", "H20"]
    latencies = []
    for _ in range(20):
        for q in queries:
            t0 = time.perf_counter()
            res = big_dict_service.search_symbols(q)
            latencies.append((time.perf_counter() - t0) * 1000)
            assert len(res) <= MAX_RESULTS  # R-23 截断护栏
    p95 = _percentile(latencies, 95)
    # 宽松阈值：只读字典 + LIKE 查询在全量规模下应显著低于 250ms
    assert p95 < 250, f"search P95={p95:.1f}ms 超过阈值"


def test_search_result_truncation(big_dict_service):
    # "600" 前缀命中数千条，必须截断到 MAX_RESULTS
    res = big_dict_service.search_symbols("600")
    assert len(res) == MAX_RESULTS


def test_search_no_realtime_akshare(big_dict_service, monkeypatch):
    # 回归护栏：新链路搜索绝不触发实时 akshare
    import akshare as ak

    def _boom(*a, **k):
        raise AssertionError("search 不应调用实时 akshare")

    for fn in ("stock_info_a_code_name", "stock_hk_spot",
               "stock_hk_ggt_components_em", "stock_zh_a_hist"):
        monkeypatch.setattr(ak, fn, _boom, raising=False)
    assert big_dict_service.search_symbols("600123")  # 不抛异常即通过


def test_full_refresh_within_budget(in_memory_db, limiter, monkeypatch):
    import akshare as ak
    a_df = pd.DataFrame(
        [(f"{600000 + i:06d}", f"公司{i}") for i in range(N_A)], columns=["code", "name"])
    hk_df = pd.DataFrame(
        [{"序号": i, "代码": f"{i:05d}", "名称": f"港股{i}"} for i in range(N_HK)])
    monkeypatch.setattr(ak, "stock_info_a_code_name", lambda: a_df, raising=False)
    monkeypatch.setattr(ak, "stock_hk_ggt_components_em", lambda: hk_df, raising=False)

    svc = DataCenterService(in_memory_db, limiter)
    stat = svc.refresh_symbol_dict()
    assert stat["replaced"] is True
    assert stat["total"] == N_A + N_HK
    # 全量刷新（含拼音生成 + 原子写入）宽松阈值 30s，实际远低于此
    assert stat["elapsed_ms"] < 30000, f"refresh 耗时 {stat['elapsed_ms']}ms 超预算"
