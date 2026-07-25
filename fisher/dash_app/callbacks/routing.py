from dash import Input, Output, callback, html, no_update
import dash_bootstrap_components as dbc
from fisher.dash_app.pages.home import create_home_layout
from fisher.dash_app.pages.data_center import create_data_center_layout

PAGE_MAP = {
    "/": create_home_layout,
    "/home": create_home_layout,
    "/data-center": create_data_center_layout,
    "/market-watch": lambda: html.Div([html.H3("行情看板"), html.P("建设中...")]),
    "/strategy-center": lambda: html.Div([html.H3("策略中心"), html.P("建设中...")]),
    "/factor-center": lambda: html.Div([html.H3("因子计算"), html.P("建设中...")]),
    "/backtest-center": lambda: html.Div([html.H3("回测中心"), html.P("建设中...")]),
    "/visual-dashboard": lambda: html.Div([html.H3("可视化看板"), html.P("建设中...")]),
    "/report-center": lambda: html.Div([html.H3("报告中心"), html.P("建设中...")]),
    "/settings": lambda: html.Div([html.H3("系统设置"), html.P("建设中...")]),
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


def register_all_callbacks(app):
    register_routing_callback(app)

    from fisher.dash_app.callbacks.home_callbacks import register_home_callbacks
    register_home_callbacks(app)

    from fisher.dash_app.callbacks.data_callbacks import register_data_callbacks
    register_data_callbacks(app)
