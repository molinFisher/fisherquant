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
            svc.reset_load()
            svc.start_background_load()
            logger.info("Auto-load triggered: empty database")
        scheduler.add_job("auto_load_daily", svc.incremental_update,
                          trigger="cron", hour=16, minute=30)
    except Exception as e:
        logger.error("Startup init failed: %s", e)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
