"""港股名称修复（issue：已缓存数据港股无名称）。

根因：refresh_symbol_dict 旧实现用 stock_hk_ggt_components_em（港股通成分），
该接口易失败，失败后整表被 A 股覆盖 → symbol_dict 仅剩 A 股，港股名称全丢；
且自动加载宇宙来自 stock_hk_spot().head(80)，与字典港股源不一致，缓存即缺名。

修复：
- refresh_symbol_dict 改用 stock_hk_spot（与自动加载同源自洽），且按市场分事务原子替换，
  港股失败不再清空 A 股、A 股失败也不再清空港股。
- 自动加载 _load_index_codes 顺带把港股名称写进 symbol_dict（缓存即可见名）。
- 新增 backfill_hk_names 修复存量已缓存港股缺名。
"""
import pandas as pd
import pytest
import akshare as ak


def _patch_hk_spot(monkeypatch, rows):
    """用真实返回格式（代码 / 中文名称）mock stock_hk_spot。"""
    def mock(*a, **k):
        return pd.DataFrame(rows)
    monkeypatch.setattr(ak, "stock_hk_spot", mock, raising=False)


class TestRefreshHkRobustness:
    def test_hk_failure_preserves_a_share_and_old_hk(self, data_service, monkeypatch):
        # 预置一条旧港股名称（模拟此前已存在）
        data_service._db.execute(
            "INSERT INTO symbol_dict (ticker, code, name, market) "
            "VALUES ('00700.HK','00700','腾讯控股','hk_connect')"
        )

        def boom(*a, **k):
            raise RuntimeError("hk source down")

        monkeypatch.setattr(ak, "stock_info_a_code_name",
                            lambda *a, **k: pd.DataFrame(
                                {"code": ["600519"], "name": ["贵州茅台"]}),
                            raising=False)
        monkeypatch.setattr(ak, "stock_hk_spot", boom, raising=False)

        stats = data_service.refresh_symbol_dict()
        # A 股应刷新成功，港股失败不应清空旧港股
        assert stats["a_share"] == 1
        assert stats["hk_connect"] == 0
        df = data_service._db.query_df(
            "SELECT ticker, name FROM symbol_dict ORDER BY ticker")
        rows = {r["ticker"]: r["name"] for r in df.iter_rows(named=True)}
        assert rows.get("600519.SH") == "贵州茅台"
        assert rows.get("00700.HK") == "腾讯控股"  # 旧港股被保留，未被清空


class TestAutoLoadUpsertHkNames:
    def test_load_index_codes_upserts_hk_names(self, auto_load_service, monkeypatch):
        # 用真实列名（代码 / 中文名称）覆盖 mock_index_cons 的简化 mock
        hk_rows = [{"日期时间": "x", "代码": f"{i:05d}", "中文名称": f"港股{i:05d}",
                    "英文名称": "X", "最新价": 1.0} for i in range(80)]
        _patch_hk_spot(monkeypatch, hk_rows)
        # 同时保证 CSI300 mock 仍在（auto_load_service fixture 已 patch）
        codes = auto_load_service._load_index_codes()
        assert any(c.endswith(".HK") for c in codes)
        # 首个港股 00001.HK 应有名称
        df = auto_load_service._db.query_df(
            "SELECT name FROM symbol_dict WHERE ticker='00001.HK'")
        assert df.height == 1
        assert df["name"][0] == "港股00001"


class TestBackfillHkNames:
    def test_backfill_fills_cached_hk_missing_names(self, data_service, monkeypatch):
        # 已缓存一个港股，但 symbol_dict 无该名称
        data_service._db.execute(
            "INSERT INTO bars_daily (ticker, trade_date, open, high, low, close, "
            "volume, amount, market) VALUES "
            "('00099.HK','2024-01-02',1.0,1.0,1.0,1.0,1,1,'hk_connect')"
        )
        _patch_hk_spot(monkeypatch, [
            {"代码": "00099", "中文名称": "美团-W"},
            {"代码": "00700", "中文名称": "腾讯控股"},
        ])
        filled = data_service.backfill_hk_names()
        assert filled == 1
        df = data_service._db.query_df(
            "SELECT name FROM symbol_dict WHERE ticker='00099.HK'")
        assert df["name"][0] == "美团-W"

    def test_backfill_no_missing_returns_zero(self, data_service, monkeypatch):
        _patch_hk_spot(monkeypatch, [{"代码": "00700", "中文名称": "腾讯控股"}])
        assert data_service.backfill_hk_names() == 0
