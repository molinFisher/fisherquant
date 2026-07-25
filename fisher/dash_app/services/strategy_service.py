import json
import logging
import os
from datetime import datetime
from pathlib import Path
from .models import StrategyConfig

logger = logging.getLogger(__name__)


class StrategyService:
    def __init__(self, strategies_dir: str):
        self._dir = Path(strategies_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, name: str) -> Path:
        safe = StrategyConfig(name=name, type="").safe_filename
        return self._dir / f"{safe}.json"

    def list_strategies(self) -> list[dict]:
        results = []
        for fp in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                results.append(data)
            except Exception as e:
                logger.warning("Failed to read %s: %s", fp.name, e)
        return results

    def get_strategy(self, name: str) -> dict | None:
        path = self._path_for(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to read strategy %s: %s", name, e)
            return None

    def save_strategy(self, config: StrategyConfig) -> dict:
        errors = config.validate()
        if errors:
            return {"status": "error", "errors": errors}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "name": config.name,
            "type": config.type,
            "description": config.description,
            "params": config.params,
            "symbols": config.symbols,
            "enabled": config.enabled,
        }

        path = self._path_for(config.name)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            data["created_at"] = existing.get("created_at", now)
        else:
            data["created_at"] = now
        data["updated_at"] = now

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "ok", "name": config.name}

    def delete_strategy(self, name: str) -> bool:
        path = self._path_for(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def toggle_enabled(self, name: str) -> dict | None:
        data = self.get_strategy(name)
        if data is None:
            return None
        data["enabled"] = not data["enabled"]
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = self._path_for(name)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def export_json(self, name: str) -> str | None:
        data = self.get_strategy(name)
        if data is None:
            return None
        return json.dumps(data, ensure_ascii=False, indent=2)

    def import_json(self, json_str: str) -> dict:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {"status": "error", "errors": [f"JSON格式错误: {e}"]}

        name = data.get("name", "")
        if not name:
            return {"status": "error", "errors": ["缺少策略名称"]}

        cfg = StrategyConfig(
            name=name,
            type=data.get("type", ""),
            description=data.get("description", ""),
            params=data.get("params", {}),
            symbols=data.get("symbols", []),
            enabled=data.get("enabled", True),
        )
        return self.save_strategy(cfg)
