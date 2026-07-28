from dash import Input, Output, State, callback, no_update, ALL
import dash_bootstrap_components as dbc
from fisher.dash_app.pages.home import create_home_layout
from fisher.dash_app.pages.data_center import create_data_center_layout
from fisher.dash_app.pages.strategy_center import create_strategy_center_layout
from fisher.dash_app.pages.factor_center import create_factor_center_layout
from fisher.dash_app.pages.backtest_center import create_backtest_center_layout
from fisher.dash_app.pages.visual_dashboard import create_visual_dashboard_layout
from fisher.dash_app.pages.report_center import create_report_center_layout
from fisher.dash_app.pages.quote_board import create_quote_board_layout
from fisher.dash_app.pages.settings import create_settings_layout

PAGE_MAP = {
    "/": create_home_layout,
    "/home": create_home_layout,
    "/data-center": create_data_center_layout,
    "/market-watch": create_quote_board_layout,
    "/strategy-center": create_strategy_center_layout,
    "/factor-center": create_factor_center_layout,
    "/backtest-center": create_backtest_center_layout,
    "/visual-dashboard": create_visual_dashboard_layout,
    "/report-center": create_report_center_layout,
    "/settings": create_settings_layout,
}

PAGE_TO_NAV_ID = {
    "/": "home",
    "/home": "home",
    "/data-center": "data-center",
    "/market-watch": "market-watch",
    "/strategy-center": "strategy-center",
    "/factor-center": "factor-center",
    "/backtest-center": "backtest-center",
    "/visual-dashboard": "visual-dashboard",
    "/report-center": "report-center",
    "/settings": "settings",
}


def register_routing_callback(app):
    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
    )
    def render_page(pathname):
        if pathname is None:
            pathname = "/"
        builder = PAGE_MAP.get(pathname, PAGE_MAP["/"])
        return builder()

    @app.callback(
        Output("sidebar-wrapper", "className"),
        Output("sidebar-container", "className"),
        Input("sidebar-toggle-btn", "n_clicks"),
        State("sidebar-wrapper", "className"),
        State("sidebar-container", "className"),
        prevent_initial_call=True,
    )
    def toggle_sidebar(n_clicks, sidebar_class, container_class):
        if n_clicks is None:
            return no_update, no_update
        sidebar_class = sidebar_class or "sidebar-wrapper"
        container_class = container_class or "sidebar-col g-0"
        if "open" in container_class:
            container_class = container_class.replace(" open", "")
        else:
            container_class = container_class + " open"
        return sidebar_class, container_class


def register_all_callbacks(app):
    register_routing_callback(app)

    from fisher.dash_app.callbacks.home_callbacks import register_home_callbacks
    register_home_callbacks(app)

    from fisher.dash_app.callbacks.data_callbacks import register_data_callbacks
    register_data_callbacks(app)

    from fisher.dash_app.callbacks.data_cache_callbacks import register_data_cache_callbacks
    register_data_cache_callbacks(app)

    from fisher.dash_app.callbacks.data_export_callbacks import register_data_export_callbacks
    register_data_export_callbacks(app)

    from fisher.dash_app.pages.data_center import register_data_center_callbacks
    register_data_center_callbacks(app)

    from fisher.dash_app.callbacks.strategy_crud_callbacks import register_strategy_crud_callbacks
    register_strategy_crud_callbacks(app)

    from fisher.dash_app.callbacks.strategy_wizard_callbacks import register_strategy_wizard_callbacks
    register_strategy_wizard_callbacks(app)

    from fisher.dash_app.callbacks.factor_callbacks import register_factor_callbacks
    register_factor_callbacks(app)

    from fisher.dash_app.callbacks.backtest_callbacks import register_backtest_callbacks
    register_backtest_callbacks(app)

    from fisher.dash_app.callbacks.viz_callbacks import register_viz_callbacks
    register_viz_callbacks(app)

    from fisher.dash_app.callbacks.report_callbacks import register_report_callbacks
    register_report_callbacks(app)

    from fisher.dash_app.callbacks.quote_callbacks import register_quote_callbacks
    register_quote_callbacks(app)

    from fisher.dash_app.callbacks.settings_callbacks import register_settings_callbacks
    register_settings_callbacks(app)
