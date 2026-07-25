import os
import re
from pathlib import Path
import yaml
from pydantic import ValidationError
from .schemas import AppConfig


class ConfigLoadError(Exception):
    pass


_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(obj):
    if isinstance(obj, str):
        def replace(match):
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                raise ConfigLoadError(f"Environment variable '{var}' not set")
            return val
        return _ENV_VAR_RE.sub(replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


_CONFIG_FILES = [
    "system.yaml", "market.yaml", "strategy.yaml",
    "risk.yaml", "fees.yaml", "alert.yaml",
    "benchmark.yaml", "broker.yaml",
]


class ConfigLoader:
    @staticmethod
    def load(config_dir: str) -> AppConfig:
        config_dir = Path(config_dir)
        raw: dict[str, dict] = {}

        for fname in _CONFIG_FILES:
            fpath = config_dir / fname
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        loaded = yaml.safe_load(f)
                    if loaded:
                        raw[fname.replace(".yaml", "")] = loaded
                except yaml.YAMLError as e:
                    raise ConfigLoadError(f"Invalid YAML in {fname}: {e}")

        raw = _resolve_env_vars(raw)

        try:
            return AppConfig(
                system=raw.get("system", {}),
                market=raw.get("market", {}),
                strategy=raw.get("strategy", {}),
                risk=raw.get("risk", {}),
                fees=raw.get("fees", {}),
                alert=raw.get("alert", {}),
                benchmark=raw.get("benchmark", {}),
                broker=raw.get("broker", {}),
            )
        except ValidationError as e:
            raise ConfigLoadError(f"Config validation failed: {e}")
