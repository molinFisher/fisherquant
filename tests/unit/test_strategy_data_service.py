"""策略中心 × 缓存联动 后端单测（对应 PRD AC-1/AC-2/AC-4/AC-5/AC-6/T1-T4）。"""
import polars as pl
import pytest

from fisher.dash_app.services.strategy_data_service import (
    StrategyDataService,
    is_a_share,
    _requires_financials,
    ReadinessReport,
    MissingItem,
)


# --------------------------------------------------------------------------- #
# 假 catalog / 假 db
# --------------------------------------------------------------------------- #
class FakeCatalog:
    def __init__(self, rows):
        self._rows = rows

    def get_cache_catalog(self, market=None, data_type=None, text=None):
        return self._rows

    def get_coverage_for_tickers(self, tickers):
        by = {r["ticker"]: r for r in self._rows}
        return {t: by[t] for t in tickers if t in by}


class FakeDB:
    """按 sql 关键字返回 bars_daily 或 adj_factors 的假结果。"""

    def __init__(self, bars, adj):
        self._bars = bars
        self._adj = adj
        self.queries = []

    def query_df(self, sql, params=None):
        self.queries.append((sql, params))
        if "FROM bars_daily" in sql:
            return self._bars
        if "FROM adj_factors" in sql:
            return self._adj
        return pl.DataFrame()


def _cat_row(ticker, daily=True, adj=False, fin=False, ds="2024-01-01", de="2024-12-31"):
    return {
        "ticker": ticker, "has_daily": daily, "has_adj": adj, "has_financials": fin,
        "daily_start": ds, "daily_end": de,
    }


# --------------------------------------------------------------------------- #
# is_a_share / _requires_financials
# --------------------------------------------------------------------------- #
def test_is_a_share():
    assert is_a_share("600519.SH") is True
    assert is_a_share("000001.SZ") is True
    assert is_a_share("123456.BJ") is True
    assert is_a_share("00700.HK") is False
    assert is_a_share("ABC") is False


def test_requires_financials_only_for_custom_dsl_keyword():
    assert _requires_financials({"type": "sma_cross"}) is False
    assert _requires_financials({"type": "custom", "params": {"dsl_config": "{}"}}) is False
    assert _requires_financials(
        {"type": "custom", "params": {"dsl_config": '{"ref": "financials.roe"}'}}
    ) is True
    assert _requires_financials(
        {"type": "custom", "params": {"dsl_config": "使用财报数据"}}
    ) is True


# --------------------------------------------------------------------------- #
# required_types_for
# --------------------------------------------------------------------------- #
def test_required_types_for():
    sds = StrategyDataService(FakeCatalog([]))
    r = sds.required_types_for({"type": "sma_cross"}, ["600519.SH", "00700.HK"])
    assert r["600519.SH"] == ["daily", "adj"]
    assert r["00700.HK"] == ["daily"]  # 港股无复权


# --------------------------------------------------------------------------- #
# check_data_readiness
# --------------------------------------------------------------------------- #
def test_readiness_all_ready():
    cat = FakeCatalog([_cat_row("600519.SH", adj=True)])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross", "symbols": ["600519.SH"]},
        "2024-01-01", "2024-12-31", ["600519.SH"],
    )
    assert rep.ready and not rep.blocking
    assert rep.status == "ready"
    assert rep.missing == []


def test_readiness_a_share_missing_adj_is_partial_when_others_ok():
    cat = FakeCatalog([
        _cat_row("600519.SH", adj=False),   # 缺 adj
        _cat_row("000001.SZ", adj=True),
    ])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross", "symbols": ["600519.SH", "000001.SZ"]},
        "2024-01-01", "2024-12-31", ["600519.SH", "000001.SZ"],
    )
    assert not rep.ready
    assert not rep.blocking            # 仅部分缺 → 仍可跑
    assert rep.status == "partial"
    miss = {m.symbol: m.types for m in rep.missing}
    assert miss["600519.SH"] == ["adj"]


def test_readiness_single_symbol_all_missing_blocks():
    cat = FakeCatalog([_cat_row("600519.SH", daily=False, adj=False)])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross", "symbols": ["600519.SH"]},
        "2024-01-01", "2024-12-31", ["600519.SH"],
    )
    assert rep.blocking                # 全缺 → 阻断
    assert rep.status == "blocked"
    assert "daily" in rep.missing[0].types
    assert "adj" in rep.missing[0].types


def test_readiness_not_in_catalog_missing():
    cat = FakeCatalog([])              # 标的根本不在 catalog
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross", "symbols": ["600519.SH"]},
        "2024-01-01", "2024-12-31", ["600519.SH"],
    )
    assert rep.blocking
    assert rep.missing[0].types == ["daily", "adj"]


def test_readiness_out_of_range():
    cat = FakeCatalog([_cat_row("600519.SH", ds="2024-06-01", de="2024-12-31")])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross", "symbols": ["600519.SH"]},
        "2024-01-01", "2024-03-31", ["600519.SH"],   # 早于缓存起点
    )
    assert rep.missing and rep.missing[0].out_of_range


def test_readiness_financials_required_by_custom_dsl():
    cat = FakeCatalog([_cat_row("600519.SH", adj=True, fin=False)])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "custom", "params": {"dsl_config": "financials.roe"},
         "symbols": ["600519.SH"]},
        "2024-01-01", "2024-12-31", ["600519.SH"],
    )
    assert any("financials" in m.types for m in rep.missing)


def test_readiness_empty_symbols_uses_cached_universe():
    cat = FakeCatalog([_cat_row("600519.SH", adj=True)])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness(
        {"type": "sma_cross"}, "2024-01-01", "2024-12-31", []
    )
    assert rep.ready                      # 空标的=全部缓存标的，有数据即就绪


def test_readiness_empty_universe_blocks():
    cat = FakeCatalog([])
    sds = StrategyDataService(cat)
    rep = sds.check_data_readiness({"type": "sma_cross"}, "2024-01-01", "2024-12-31", [])
    assert rep.blocking and not rep.ready


# --------------------------------------------------------------------------- #
# load_adjusted_bars（P0-2 复权注入）
# --------------------------------------------------------------------------- #
def test_load_adjusted_bars_applies_qfq():
    bars = pl.DataFrame({
        "ticker": ["600519.SH", "600519.SH"],
        "trade_date": ["2024-01-02", "2024-01-03"],
        "open": [100.0, 110.0],
        "high": [105.0, 115.0],
        "low": [95.0, 105.0],
        "close": [100.0, 110.0],
        "volume": [1000, 1100],
        "amount": [1.0, 1.1],
        "market": ["a_share", "a_share"],
    })
    adj = pl.DataFrame({
        "trade_date": ["2024-01-02", "2024-01-03"],
        "adj_factor": [2.0, 2.2],
    })
    db = FakeDB(bars, adj)
    sds = StrategyDataService(FakeCatalog([]), db=db)
    out = sds.load_adjusted_bars("600519.SH", "2024-01-01", "2024-12-31", "qfq")
    assert len(out) == 2
    # adjusted = raw / factor
    assert abs(out["close"][0] - 50.0) < 1e-6
    assert abs(out["close"][1] - 50.0) < 1e-6
    assert abs(out["open"][0] - 50.0) < 1e-6
    # schema 顺序与 _load_bars 一致
    assert out.columns == ["ticker", "trade_date", "open", "high", "low",
                            "close", "volume", "amount", "market"]


def test_load_adjusted_bars_non_a_share_raw():
    bars = pl.DataFrame({
        "ticker": ["00700.HK"],
        "trade_date": ["2024-01-02"],
        "open": [100.0], "high": [105.0], "low": [95.0], "close": [100.0],
        "volume": [1000], "amount": [1.0], "market": ["hk_connect"],
    })
    db = FakeDB(bars, pl.DataFrame())
    sds = StrategyDataService(FakeCatalog([]), db=db)
    out = sds.load_adjusted_bars("00700.HK", "2024-01-01", "2024-12-31", "qfq")
    assert out["close"][0] == 100.0        # 非 A 股不调整


# --------------------------------------------------------------------------- #
# cache_range_for（P0-3 并集边界）
# --------------------------------------------------------------------------- #
def test_cache_range_for_union():
    cat = FakeCatalog([
        _cat_row("600519.SH", ds="2024-01-01", de="2024-06-30"),
        _cat_row("000001.SZ", ds="2024-03-01", de="2024-12-31"),
    ])
    sds = StrategyDataService(cat)
    start, end = sds.cache_range_for({"symbols": ["600519.SH", "000001.SZ"]})
    assert start == "2024-01-01"
    assert end == "2024-12-31"


def test_cache_range_for_fallback_when_empty():
    cat = FakeCatalog([])
    sds = StrategyDataService(cat)
    start, end = sds.cache_range_for({"symbols": []})
    assert start == "2024-01-01"
    assert end >= "2024-01-01"
