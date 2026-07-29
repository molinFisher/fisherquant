"""G4 合规日志（沙盒内可审计）。

全链路结构化留痕：下单、撤单、成交、风控拦截。支持内存收集（便于测试/查询）
与可选 JSONL 文件落地（便于留存与穿透式审计）。
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AuditLogger:
    def __init__(self, filepath: str | None = None):
        self._records: list[dict] = []
        self._filepath = filepath

    def log(self, event_type: str, **fields) -> dict:
        rec = {"event": event_type, "ts": datetime.now(timezone.utc).isoformat()}
        rec.update(fields)
        self._records.append(rec)
        if self._filepath:
            try:
                with open(self._filepath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError as e:  # noqa: BLE001
                logger.warning("AuditLogger: 写入文件失败 (%s)", e)
        return rec

    @property
    def records(self) -> list[dict]:
        return self._records

    def query(self, event_type: str | None = None) -> list[dict]:
        if event_type is None:
            return list(self._records)
        return [r for r in self._records if r.get("event") == event_type]

    def clear(self) -> None:
        self._records.clear()
