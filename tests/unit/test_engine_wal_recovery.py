"""DuckDB WAL 损坏自恢复回归测试（PRD §16.13）。

验证 engine.DuckDBManager 在 WAL 文件损坏时：
- 策略 1：仅丢弃损坏 WAL、保留主库已提交数据（不丢缓存 / 标的字典）；
- 策略 2（兜底）：主库本身也损坏时才备份主库并建空库，且不抛异常。

修复前的行为是「无论 WAL 还是主库损坏都直接备份主库建空库」，
曾导致一次重启清空全部缓存与 symbol_dict，搜索无结果。
"""
import os
import tempfile
import duckdb

from fisher.store.engine import DuckDBManager


def _reset_singleton():
    DuckDBManager._instance = None


def _make_good_db(path: str):
    con = duckdb.connect(path)
    con.execute("CREATE TABLE symbol_dict (ticker VARCHAR, name VARCHAR)")
    con.execute(
        "INSERT INTO symbol_dict VALUES "
        "('600519.SH','贵州茅台'),('09926.HK','康方生物')"
    )
    con.close()  # 默认 checkpoint，主库文件一致


def test_wal_only_corruption_preserves_data():
    """仅 WAL 损坏 → 保留主库，symbol_dict 数据不丢。"""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "keep.db")
    _make_good_db(db_path)

    # 模拟重启后残留的损坏 WAL
    with open(db_path + ".wal", "wb") as f:
        f.write(b"GARBAGE CORRUPT WAL\x00\x01\x02")

    _reset_singleton()
    mgr = DuckDBManager(db_path)
    mgr.connect(db_path)

    cnt = mgr.execute("SELECT COUNT(*) FROM symbol_dict").fetchone()[0]
    assert cnt == 2, f"WAL 损坏恢复后数据丢失：期望 2 行，实际 {cnt}"
    # 数据确实可读
    names = {r[0] for r in mgr.execute("SELECT name FROM symbol_dict").fetchall()}
    assert "贵州茅台" in names and "康方生物" in names
    mgr.close()
    _reset_singleton()


def test_main_corruption_falls_back_to_empty_rebuild():
    """主库本身损坏 → 兜底备份主库并建空库，且不抛异常。"""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "fallback.db")
    _make_good_db(db_path)

    # 主库与 WAL 都写垃圾
    with open(db_path, "wb") as f:
        f.write(b"CORRUPT MAIN FILE")
    with open(db_path + ".wal", "wb") as f:
        f.write(b"more garbage")

    _reset_singleton()
    mgr = DuckDBManager(db_path)
    mgr.connect(db_path)  # 不应抛异常
    # 空库重建后连接可用（symbol_dict 可能不存在，确认不崩溃即可）
    ok = mgr.execute("SELECT 1").fetchone()[0]
    assert ok == 1
    mgr.close()
    _reset_singleton()
