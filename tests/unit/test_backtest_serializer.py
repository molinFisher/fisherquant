"""BacktestSerializer 单元级测试：覆盖此前 24% 未覆盖的文件 round-trip / 历史库路径。

要点：
- save 落盘 equity_curve.parquet + metadata.json（含传入字段与自动字段）；
- benchmark / trades 可选写入；
- load 反序列化（含 partial 缺失文件不报错）；
- metadata 透传新字段 adj_caliber（P0-2 复权口径留痕可追溯）；
- list_history / cleanup 经 FakeDB 验证（含 DB 异常降级为 []）。
"""
import json
from pathlib import Path

import polars as pl
import pytest

from fisher.backtest import serializer as ser_mod
from fisher.backtest.serializer import BacktestSerializer


class _FakeDB:
    def __init__(self):
        self.executed = []
        self.history = []  # 行：dict

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "INSERT OR REPLACE INTO backtest_history" in sql and params:
            cols = ["id", "saved_at", "strategy", "total_return", "sharpe", "max_dd"]
            self.history.append(dict(zip(cols, params)))
        elif "DELETE FROM backtest_history" in sql and params:
            # ORDER BY saved_at ASC LIMIT ? -> 删最旧 ? 行，保留其余
            limit = params[0]
            self.history = self.history[limit:]

    def query_df(self, sql, params=None):
        if "COUNT" in sql:
            return pl.DataFrame({"c": [len(self.history)]})
        if self.history:
            return pl.DataFrame(self.history)
        return pl.DataFrame({
            "id": [], "saved_at": [], "strategy": [],
            "total_return": [], "sharpe": [], "max_dd": [],
        })


@pytest.fixture
def ser(tmp_path, monkeypatch):
    monkeypatch.setattr(ser_mod, "RESULTS_DIR", str(tmp_path / "results"))
    db = _FakeDB()
    s = BacktestSerializer(db=db)
    s._db = db
    return s, db


def test_save_writes_equity_and_metadata(ser):
    s, db = ser
    nav = [1.0, 1.01, 1.02]
    path = s.save("r1", nav, metadata={"strategy": "bh", "total_return": 0.02})
    base = Path(path)
    assert (base / "equity_curve.parquet").exists()
    assert (base / "metadata.json").exists()
    meta = json.loads((base / "metadata.json").read_text())
    assert meta["id"] == "r1"
    assert meta["nav_points"] == 3
    assert meta["strategy"] == "bh"
    assert meta["total_return"] == 0.02
    assert any("backtest_history" in sql for sql, _ in db.executed)


def test_save_with_benchmark_and_trades(ser):
    s, _ = ser
    s.save("r2", [1.0, 1.1], benchmark=[1.0, 1.05],
           trades=[{"ticker": "600519.SH", "pnl": 0.1}],
           metadata={"strategy": "bh"})
    base = Path(ser_mod.RESULTS_DIR) / "r2"
    assert (base / "benchmark_curve.parquet").exists()
    assert (base / "trades.parquet").exists()


def test_round_trip_load(ser):
    s, _ = ser
    nav = [1.0, 1.1, 1.2, 1.15]
    bench = [1.0, 1.02, 1.04, 1.01]
    trades = [{"ticker": "600519.SH", "pnl": 0.1}]
    s.save("rt", nav, trades=trades, benchmark=bench,
           metadata={"strategy": "bh", "adj_caliber": {"600519.SH": "qfq"}})
    out = s.load("rt")
    assert out["id"] == "rt"
    assert out["equity"] == nav
    assert out["benchmark"] == bench
    assert out["trades"] == trades
    # metadata 透传 adj_caliber
    assert out["metadata"]["adj_caliber"] == {"600519.SH": "qfq"}


def test_load_missing_files_is_partial(ser):
    s, _ = ser
    s.save("partial", [1.0, 2.0])
    base = Path(ser_mod.RESULTS_DIR) / "partial"
    # 删除可选文件，模拟 partial 场景
    (base / "benchmark_curve.parquet").unlink(missing_ok=True)
    (base / "trades.parquet").unlink(missing_ok=True)
    out = s.load("partial")
    assert out["equity"] == [1.0, 2.0]
    assert "benchmark" not in out
    assert "trades" not in out


def test_list_history_returns_rows(ser):
    s, db = ser
    s.save("h1", [1.0], metadata={"strategy": "bh"})
    s.save("h2", [1.0], metadata={"strategy": "bh"})
    rows = s.list_history(limit=10)
    assert len(rows) == 2
    assert {r["id"] for r in rows} == {"h1", "h2"}


def test_list_history_db_error_returns_empty(ser, monkeypatch):
    s, db = ser
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "query_df", boom)
    assert s.list_history() == []


def test_cleanup_keeps_newest(ser):
    s, db = ser
    for i in range(5):
        s.save(f"c{i}", [1.0], metadata={"strategy": "bh"})
    assert len(db.history) == 5
    s.cleanup(keep=2)
    # 删最旧 3 行，保留最新 2
    assert len(db.history) == 2
    assert {r["id"] for r in db.history} == {"c3", "c4"}


def test_cleanup_noop_when_under_limit(ser):
    s, db = ser
    s.save("x1", [1.0], metadata={"strategy": "bh"})
    before = len(db.history)
    s.cleanup(keep=200)
    assert len(db.history) == before
