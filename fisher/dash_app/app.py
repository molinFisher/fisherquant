import dash
import dash_bootstrap_components as dbc
from diskcache import Cache
from fisher.dash_app.layout import create_layout
from fisher.dash_app.callbacks.routing import register_all_callbacks

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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
