"""G4 合规日志直测：AuditLogger 内存收集 + JSONL 落地 + 查询过滤。

覆盖点：
- log 返回结构化记录（event/ts/自定义字段）；
- records 累积与 query 按事件类型过滤；
- 指定 filepath 时以 JSONL 追加写入，且可重新读取；
- clear 清空内存（不影响已落盘文件，符合"留痕"语义）。
"""
import json

import pytest

from fisher.risk.audit import AuditLogger


def test_log_returns_structured_record():
    al = AuditLogger()
    rec = al.log("submit", order_id="O1", ticker="600519.SH")
    assert rec["event"] == "submit"
    assert "ts" in rec
    assert rec["order_id"] == "O1"
    assert rec["ticker"] == "600519.SH"


def test_records_accumulate():
    al = AuditLogger()
    al.log("submit", order_id="O1")
    al.log("fill", order_id="O1", qty=100)
    assert len(al.records) == 2


def test_query_filters_by_event():
    al = AuditLogger()
    al.log("submit", order_id="O1")
    al.log("fill", order_id="O1")
    al.log("submit", order_id="O2")
    submits = al.query("submit")
    assert len(submits) == 2
    assert all(r["event"] == "submit" for r in submits)
    fills = al.query("fill")
    assert len(fills) == 1
    # None 返回全部
    assert len(al.query(None)) == 3


def test_jsonl_persistence(tmp_path):
    fp = tmp_path / "audit.jsonl"
    al = AuditLogger(filepath=str(fp))
    al.log("submit", order_id="O1")
    al.log("cancel", order_id="O1")
    assert fp.exists()
    lines = fp.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    loaded = [json.loads(ln) for ln in lines]
    assert loaded[0]["event"] == "submit"
    assert loaded[1]["event"] == "cancel"


def test_clear_keeps_file(tmp_path):
    fp = tmp_path / "audit.jsonl"
    al = AuditLogger(filepath=str(fp))
    al.log("submit", order_id="O1")
    al.clear()
    assert al.records == []
    # 已落盘内容保留（穿透式留痕）
    assert fp.exists()
    assert len(fp.read_text(encoding="utf-8").strip().splitlines()) == 1
    # clear 后继续写入仍可追加
    al.log("fill", order_id="O1")
    assert len(fp.read_text(encoding="utf-8").strip().splitlines()) == 2
