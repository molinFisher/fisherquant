import copy
import logging
import os
import re
from pathlib import Path
import yaml
from pydantic import ValidationError
from .schemas import AppConfig


class ConfigLoadError(Exception):
    pass


logger = logging.getLogger(__name__)


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
    return copy.deepcopy(obj)


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
                except (yaml.YAMLError, OSError) as e:
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

    @staticmethod
    def safe_load(config_dir: str) -> tuple[AppConfig, list[str]]:
        """加载配置；遇到损坏/非法配置时回退默认配置并产出告警（PRD §16.14）。

        返回 (config, warnings)：
        - 正常：返回解析后的 AppConfig，warnings 为空。
        - 损坏/校验失败：记录告警并返回 AppConfig() 默认配置，不向外抛异常，
          保证看板/服务在配置损坏时仍可启动。
        """
        warnings: list[str] = []
        try:
            return ConfigLoader.load(config_dir), warnings
        except ConfigLoadError as e:
            msg = f"配置加载失败，已回退默认配置: {e}"
            warnings.append(msg)
            logger.warning(msg)
            return AppConfig(), warnings
        except Exception as e:  # 兜底：任何意外错误都不应阻断启动
            msg = f"配置加载发生未知错误，已回退默认配置: {e}"
            warnings.append(msg)
            logger.warning(msg)
            return AppConfig(), warnings
