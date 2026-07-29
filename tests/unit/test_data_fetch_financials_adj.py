"""数据获取：财务数据宽表转换 + 复权因子推导（akshare 1.18 兼容）。

覆盖两个真实 bug：
- 财务：stock_financial_abstract 返回宽表（指标为行、YYYYMMDD 为列），旧逻辑把
  「选项」误当日期列导致全部行被跳过 → 误报「无财务数据」。
- 复权：akshare 1.18 不再支持 adjust='qfq_factor'/'hfq_factor'（返回空），需由
  不复权/前复权/后复权 三收盘价序列推导 qfq/hfq 因子。
"""
import pandas as pd
import pytest

from fisher.store.engine import DuckDBManager
from fisher.store.schema import init_schema
from fisher.market.rate_limiter import RateLimiter
from fisher.dash_app.services.data_center_service import DataCenterService
import fisher.dash_app.services.data_center_service as dcs


def _make_service(tmp_path):
    db = DuckDBManager(str(tmp_path / "dc.db"))
    db.connect(str(tmp_path / "dc.db"), read_pool_size=2)
    init_schema(db)
    svc = DataCenterService(db, RateLimiter())
    return db, svc


def test_convert_financials_wide_table():
    df = pd.DataFrame({
        "选项": ["常用指标", "常用指标"],
        "指标": ["归母净利润", "营业总收入"],
        "20260331": [2.7e10, 5.4e10],
        "20251231": [8.2e10, 1.7e11],
    })
    rows, fin_end = DataCenterService._convert_financials("600519.SH", df)
    # 2 指标 × 2 报告期 = 4 行；按 (报告期,指标) 去重后仍为 4
    assert len(rows) == 4, rows
    assert fin_end == "2026-03-31"
    for r in rows:
        ticker, rd, rt, ind, val, unit = r
        assert ticker == "600519.SH"
        assert len(rd) == 10 and rd[4] == "-"  # YYYY-MM-DD
        assert rt in ("一季报", "年报")
        assert ind in ("归母净利润", "营业总收入")
        assert val > 0


def test_fetch_financials_writes_table(tmp_path, monkeypatch):
    db, svc = _make_service(tmp_path)

    def fake_abstract(symbol=None):
        return pd.DataFrame({
            "选项": ["常用指标", "常用指标"],
            "指标": ["归母净利润", "营业总收入"],
            "20260331": [2.7e10, 5.4e10],
            "20251231": [8.2e10, 1.7e11],
        })

    monkeypatch.setattr(dcs.ak, "stock_financial_abstract", fake_abstract)

    res = svc.fetch_bars(["600519.SH"], "2020-01-01", "2026-12-31", "financials")
    assert res["600519.SH"]["status"] == "ok", res
    cnt = db.query_df("SELECT COUNT(*) AS c FROM financials WHERE ticker='600519.SH'")["c"][0]
    assert cnt == 4, cnt
    # catalog 标记 has_financials
    has = db.query_df(
        "SELECT has_financials, fin_report_end FROM cache_catalog WHERE ticker='600519.SH'"
    )
    assert has["has_financials"][0] is True
    assert str(has["fin_report_end"][0])[:10] == "2026-03-31"


def test_fetch_adj_derives_factors(tmp_path, monkeypatch):
    db, svc = _make_service(tmp_path)

    def fake_daily(symbol=None, start_date=None, end_date=None, adjust=""):
        dates = ["2024-01-02", "2024-01-03"]
        if adjust == "":
            closes = [100.0, 101.0]
        elif adjust == "qfq":
            closes = [95.0, 96.0]
        elif adjust == "hfq":
            closes = [110.0, 111.0]
        else:
            closes = [100.0, 101.0]
        return pd.DataFrame({
            "date": pd.to_datetime(dates),
            "open": closes, "high": closes, "low": closes,
            "close": closes, "volume": [1, 1], "amount": [1.0, 1.0],
        })

    monkeypatch.setattr(dcs.ak, "stock_zh_a_daily", fake_daily)

    res = svc.fetch_bars(["600519.SH"], "2024-01-01", "2024-01-31", "adj")
    assert res["600519.SH"]["status"] == "ok", res

    rows = db.query_df(
        "SELECT trade_date, adj_type, adj_factor FROM adj_factors "
        "WHERE ticker='600519.SH' ORDER BY trade_date, adj_type"
    ).to_dicts()
    assert len(rows) == 4, rows  # 2 日期 × 2 口径
    by_key = {(str(r["trade_date"]), r["adj_type"]): r["adj_factor"] for r in rows}
    # qfq_factor = raw / qfq；hfq_factor = raw / hfq
    assert abs(by_key[("2024-01-02", "qfq")] - 100.0 / 95.0) < 1e-6
    assert abs(by_key[("2024-01-02", "hfq")] - 100.0 / 110.0) < 1e-6
    assert abs(by_key[("2024-01-03", "qfq")] - 101.0 / 96.0) < 1e-6
    assert abs(by_key[("2024-01-03", "hfq")] - 101.0 / 111.0) < 1e-6
    # catalog 标记 has_adj
    has = db.query_df("SELECT has_adj FROM cache_catalog WHERE ticker='600519.SH'")
    assert has["has_adj"][0] is True
