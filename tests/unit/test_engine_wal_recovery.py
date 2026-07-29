"""DuckDB WAL / 主库损坏自恢复回归测试（PRD §16.13）。

验证 engine.DuckDBManager 在文件损坏时：
- 策略 1：仅丢弃损坏 WAL、保留主库已提交数据（不丢缓存 / 标的字典）；
- 策略 2（兜底）：主库本身也损坏时**拒绝重建空库**（抛 RuntimeError 并原地保留
  原文件），绝不静默清空缓存。

修复前的行为是「无论 WAL 还是主库损坏都直接把主库挪成 .corrupt 并建空库」，
曾累计 9 次重启清空全部缓存与 symbol_dict，搜索无结果。
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


def test_lock_conflict_never_rebuilds(monkeypatch):
    """另一进程持有 DuckDB 锁 → 抛异常拒绝重建，主库文件与数据必须原样保留。

    修复前：锁冲突被误判为「库损坏」，好库被挪成 .corrupt 并新建空库，
    Flask reloader 双进程 / 外部诊断脚本都会随机触发清库（搜索无结果）。
    注：DuckDB 同进程内共享实例不会撞锁（锁冲突只发生在跨进程），
    故用 monkeypatch 模拟跨进程锁异常。
    """
    import pytest
    from fisher.store import engine as engine_mod

    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "locked.db")
    _make_good_db(db_path)

    real_connect = duckdb.connect

    def fake_connect(path, *a, **kw):
        if str(path) == db_path:
            raise duckdb.IOException(
                f'Could not set lock on file "{db_path}": '
                "Conflicting lock is held by another process (PID 99999)")
        return real_connect(path, *a, **kw)

    monkeypatch.setattr(engine_mod.duckdb, "connect", fake_connect)

    _reset_singleton()
    try:
        with pytest.raises(Exception) as ei:
            # 构造即连接，锁冲突应直接抛出而非重建
            mgr = DuckDBManager(db_path)
            mgr.connect(db_path)
        # 必须是锁冲突类异常，而非静默重建
        assert "lock" in str(ei.value).lower()
        # 主库文件原地未动、未产生 .corrupt 备份
        assert os.path.exists(db_path), "主库文件被挪走了！"
        siblings = os.listdir(tmp)
        assert not any(".corrupt." in s for s in siblings), \
            f"锁冲突不应产生 corrupt 备份：{siblings}"
    finally:
        _reset_singleton()

    # 锁"释放"（还原 connect）后数据完好
    con = real_connect(db_path, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM symbol_dict").fetchone()[0] == 2
    con.close()


def test_main_corruption_raises_without_wiping():
    """主库本身损坏 → 拒绝重建空库以免清空缓存：抛异常且原文件原地保留、不产生 .corrupt 备份。

    修复前：主库损坏会被挪成 .corrupt 并新建空库，清空全部缓存与标的字典。
    现改为保留原文件并抛出 RuntimeError，由运维从 .corrupt 历史备份手动恢复。
    """
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "fallback.db")
    _make_good_db(db_path)

    # 主库与 WAL 都写垃圾
    with open(db_path, "wb") as f:
        f.write(b"CORRUPT MAIN FILE")
    with open(db_path + ".wal", "wb") as f:
        f.write(b"more garbage")

    _reset_singleton()
    import pytest

    with pytest.raises(RuntimeError) as ei:
        mgr = DuckDBManager(db_path)
        mgr.connect(db_path)  # 应抛 RuntimeError，绝不静默建空库
    assert "未清空缓存" in str(ei.value) or "保留" in str(ei.value)

    # 原文件原地保留、内容未变，且未产生 .corrupt 备份
    assert os.path.exists(db_path), "主库文件被挪走了！"
    with open(db_path, "rb") as f:
        assert f.read() == b"CORRUPT MAIN FILE"
    siblings = os.listdir(tmp)
    assert not any(".corrupt." in s for s in siblings), \
        f"主库损坏不应产生 corrupt 备份（应保留原文件）：{siblings}"
    _reset_singleton()
