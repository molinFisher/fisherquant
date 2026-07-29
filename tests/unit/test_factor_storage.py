"""因子存储直测：FactorStorage 保存/读取/合并/删除 + 列名清洗。

覆盖点：
- sanitize_column 清洗特殊字符并小写；
- save 新建 + load 往返；
- save 同标的再次写入时按列合并（已存在列被覆盖更新，而非重复追加）；
- delete 删除目录；
- load_with_factors 与 OHLCV 对齐拼接，因子缺失时回退原表。
"""
import polars as pl
import pytest

import fisher.factor.storage as storage
from fisher.factor.storage import FactorStorage, sanitize_column


@pytest.fixture
def factor_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "FACTOR_DIR", str(tmp_path / "factors"))
    return tmp_path / "factors"


def test_sanitize_column():
    assert sanitize_column("MA(20)") == "ma_20_"
    assert sanitize_column("RSI-14") == "rsi_14"
    assert sanitize_column("Close#Price") == "close_price"


def test_save_and_load_roundtrip(factor_dir):
    df = pl.DataFrame({"ma20": [1.0, 2.0], "rsi": [30.0, 40.0]})
    FactorStorage.save("600519.SH", df)
    out = FactorStorage.load("600519.SH")
    assert out is not None
    assert set(out.columns) == {"ma20", "rsi"}
    assert out.height == 2


def test_save_merges_columns(factor_dir):
    df1 = pl.DataFrame({"ma20": [1.0, 2.0]})
    df2 = pl.DataFrame({"rsi": [30.0, 40.0]})
    FactorStorage.save("600519.SH", df1)
    FactorStorage.save("600519.SH", df2)
    out = FactorStorage.load("600519.SH")
    assert set(out.columns) == {"ma20", "rsi"}
    assert out.height == 2


def test_save_updates_existing_column(factor_dir):
    df1 = pl.DataFrame({"ma20": [1.0, 2.0]})
    df2 = pl.DataFrame({"ma20": [9.0, 8.0], "rsi": [30.0, 40.0]})
    FactorStorage.save("600519.SH", df1)
    FactorStorage.save("600519.SH", df2)
    out = FactorStorage.load("600519.SH")
    # ma20 被更新为 df2 的值，且不多列
    assert out["ma20"].to_list() == [9.0, 8.0]
    assert set(out.columns) == {"ma20", "rsi"}


def test_delete(factor_dir):
    FactorStorage.save("600519.SH", pl.DataFrame({"ma20": [1.0]}))
    assert FactorStorage.load("600519.SH") is not None
    FactorStorage.delete("600519.SH")
    assert FactorStorage.load("600519.SH") is None


def test_load_with_factors_fallback_and_merge(factor_dir):
    ohlcv = pl.DataFrame({"close": [10.0, 11.0, 12.0]})
    # 无因子文件 -> 直接回退原表
    assert FactorStorage.load_with_factors("NONE.SH", ohlcv).equals(ohlcv)
    # 有因子 -> 按最短长度对齐拼接
    FactorStorage.save("600519.SH", pl.DataFrame({"ma20": [1.0, 2.0]}))
    merged = FactorStorage.load_with_factors("600519.SH", ohlcv)
    assert "ma20" in merged.columns
    assert merged.height == 2  # 受因子长度约束
