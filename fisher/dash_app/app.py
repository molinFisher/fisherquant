import dash
import dash_bootstrap_components as dbc
import logging
from diskcache import Cache
from fisher.dash_app.layout import create_layout
from fisher.dash_app.callbacks.routing import register_all_callbacks
from fisher.scheduler.engine import SchedulerEngine

logger = logging.getLogger(__name__)

cache = Cache("./data/dash_cache")
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    background_callback_manager=dash.DiskcacheManager(cache),
    suppress_callback_exceptions=True,
)
app.title = "FisherQuant"
app._favicon = "favicon.svg"
app.layout = create_layout()
register_all_callbacks(app)

# Scheduler for background tasks
scheduler = SchedulerEngine()
scheduler.start()

# Startup initialization flag
_startup_done = False


@app.server.before_request
def init_on_startup():
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    try:
        from fisher.dash_app.services import get_auto_load_service
        svc = get_auto_load_service(scheduler)
        # 空库或表尚未创建时都应触发初始加载；count 查询异常按空库处理
        try:
            count = int(svc._db.query_df("SELECT COUNT(*) as c FROM bars_daily")["c"].to_list()[0])
        except Exception:
            count = 0
        if count == 0:
            svc.recover()
            logger.info("Auto-load triggered: empty database (recover)")
        else:
            svc.recover()
        scheduler.add_job("auto_load_daily", svc.incremental_update,
                          trigger="cron", hour=16, minute=30)
    except Exception as e:
        logger.error("Startup init failed: %s", e)

    # R-13：标的字典交易日定时刷新（默认 08:30，可由 configs/system.yaml 覆盖）
    # R-02：冷启动兜底——字典为空时后台立即刷新一次，避免首用搜索无结果
    try:
        import threading
        from fisher.dash_app.services import get_data_service
        from fisher.config.loader import ConfigLoader

        data_svc = get_data_service()
        cfg, _ = ConfigLoader.safe_load("configs")
        refresh_at = getattr(cfg.system.search, "dict_refresh_time", "08:30") or "08:30"
        try:
            hh, mm = (int(x) for x in refresh_at.split(":", 1))
        except Exception:
            hh, mm = 8, 30
        scheduler.add_job("symbol_dict_refresh", data_svc.refresh_symbol_dict,
                          trigger="cron", day_of_week="mon-fri", hour=hh, minute=mm)
        logger.info("已登记标的字典刷新任务：交易日 %02d:%02d", hh, mm)

        try:
            dict_count = int(
                data_svc._db.query_df("SELECT COUNT(*) as c FROM symbol_dict")["c"].to_list()[0]
            )
        except Exception:
            dict_count = 0
        if dict_count == 0:
            threading.Thread(
                target=data_svc.refresh_symbol_dict, name="symbol_dict_cold_start",
                daemon=True,
            ).start()
            logger.info("标的字典为空，已触发冷启动后台刷新")
    except Exception as e:
        logger.error("标的字典刷新调度初始化失败: %s", e)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
