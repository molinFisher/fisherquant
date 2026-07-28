import logging
from pathlib import Path
from ...store.engine import DuckDBManager
from ...store.schema import init_schema
from ...market.rate_limiter import RateLimiter, get_global_limiter

logger = logging.getLogger(__name__)

_db_instance: DuckDBManager | None = None
_limiter_instance: RateLimiter | None = None
_data_service_instance = None
_auto_load_service_instance = None
_strategy_service_instance = None
_cache_catalog_service_instance = None


def get_db() -> DuckDBManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DuckDBManager()
        db_path = str(Path("./data/fisherquant.db").resolve())
        try:
            _db_instance.connect(db_path, read_pool_size=4)
            init_schema(_db_instance)
        except Exception as e:
            logger.error("Failed to connect DB: %s", e)
    elif not hasattr(_db_instance, '_write_conn') or _db_instance._write_conn is None:
        db_path = str(Path("./data/fisherquant.db").resolve())
        try:
            _db_instance.connect(db_path, read_pool_size=4)
            init_schema(_db_instance)
        except Exception as e:
            logger.error("Failed to reconnect DB: %s", e)
    return _db_instance


def get_limiter() -> RateLimiter:
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = get_global_limiter()
    return _limiter_instance


def get_data_service():
    global _data_service_instance
    if _data_service_instance is None:
        from .data_center_service import DataCenterService
        _data_service_instance = DataCenterService(get_db(), get_limiter())
    return _data_service_instance


def get_auto_load_service(scheduler=None):
    global _auto_load_service_instance
    if _auto_load_service_instance is None:
        from .auto_load_service import AutoLoadService
        _auto_load_service_instance = AutoLoadService(get_db(), get_limiter(), scheduler)
    return _auto_load_service_instance


def get_cache_catalog_service() -> "CacheCatalogService":
    global _cache_catalog_service_instance
    if _cache_catalog_service_instance is None:
        from .cache_catalog_service import CacheCatalogService
        _cache_catalog_service_instance = CacheCatalogService(get_db())
    return _cache_catalog_service_instance


def get_strategy_service(strategies_dir: str | None = None):
    global _strategy_service_instance
    if _strategy_service_instance is None:
        from .strategy_service import StrategyService
        base_dir = strategies_dir or str(Path("./strategies").resolve())
        _strategy_service_instance = StrategyService(base_dir)
    return _strategy_service_instance
