"""Phase 3 结构性断言：13 个回调模块的注册、routing 映射、layout/pages 组件存在性。

区别于仅校验 HTTP 200 的集成冒烟，这里直接 import 并注册全部回调，验证：
  - register_all_callbacks 注册的回调数量（>=60）
  - routing.PAGE_MAP / PAGE_TO_NAV_ID 完整且自洽
  - create_layout() 包含 page-content 路由出口
  - 9 个页面布局均可成功构建（组件存在）
"""
import pytest

from fisher.dash_app.callbacks.routing import (
    register_all_callbacks, PAGE_MAP, PAGE_TO_NAV_ID,
)
from fisher.dash_app.layout import create_layout
from tests.helpers.dash_harness import capture_dash_callbacks

from fisher.dash_app.pages.home import create_home_layout
from fisher.dash_app.pages.data_center import create_data_center_layout
from fisher.dash_app.pages.strategy_center import create_strategy_center_layout
from fisher.dash_app.pages.factor_center import create_factor_center_layout
from fisher.dash_app.pages.backtest_center import create_backtest_center_layout
from fisher.dash_app.pages.visual_dashboard import create_visual_dashboard_layout
from fisher.dash_app.pages.report_center import create_report_center_layout
from fisher.dash_app.pages.quote_board import create_quote_board_layout
from fisher.dash_app.pages.settings import create_settings_layout


class TestCallbackRegistration:
    def test_all_callbacks_register(self):
        with capture_dash_callbacks() as app:
            register_all_callbacks(app)
        # 13 个回调模块合计 69 个回调；阈值留余量
        assert app.callback_count() >= 60

    def test_backtest_main_callback_registered(self):
        with capture_dash_callbacks() as app:
            register_all_callbacks(app)
        # 主回测回调的输出组件
        cb = app.get_callback("bt-progress-bar")
        assert callable(cb)

    def test_routing_callback_registered(self):
        with capture_dash_callbacks() as app:
            register_all_callbacks(app)
        cb = app.get_callback("page-content")
        assert callable(cb)


class TestRoutingMap:
    def test_page_map_has_nine_routes(self):
        expected = {
            "/", "/home", "/data-center", "/market-watch", "/strategy-center",
            "/factor-center", "/backtest-center", "/visual-dashboard",
            "/report-center", "/settings",
        }
        assert expected.issubset(set(PAGE_MAP.keys()))

    def test_nav_ids_map_to_pages(self):
        for nav_id in PAGE_TO_NAV_ID.values():
            assert nav_id in PAGE_MAP or nav_id in (
                "data-center", "market-watch", "strategy-center",
                "factor-center", "backtest-center", "visual-dashboard",
                "report-center", "settings",
            )


class TestLayoutAndPages:
    def test_layout_has_page_content_outlet(self):
        layout = create_layout()
        assert layout is not None
        # 路由出口 page-content 存在于布局中
        found = []

        def _walk(node):
            if hasattr(node, "id") and node.id == "page-content":
                found.append(True)
            children = getattr(node, "children", None)
            if isinstance(children, (list, tuple)):
                for c in children:
                    _walk(c)
            elif children is not None:
                _walk(children)

        _walk(layout)
        assert found, "layout 应包含 id='page-content' 的路由出口"

    @pytest.mark.parametrize("builder", [
        create_home_layout, create_data_center_layout, create_strategy_center_layout,
        create_factor_center_layout, create_backtest_center_layout,
        create_visual_dashboard_layout, create_report_center_layout,
        create_quote_board_layout, create_settings_layout,
    ])
    def test_each_page_builds(self, builder):
        comp = builder()
        assert comp is not None
        # 是一个 dash 组件（具备 children 或 id）
        assert hasattr(comp, "children") or hasattr(comp, "id")
