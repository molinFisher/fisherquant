"""全站导航与路由冒烟测试。"""
import pytest

from ui_helpers import (
    PAGE_SIGNATURE,
    assert_no_page_errors,
    click_nav,
    goto,
)

ROUTES = list(PAGE_SIGNATURE.keys())


@pytest.mark.parametrize("path", ROUTES, ids=ROUTES)
def test_deep_link_route_renders(ui, path):
    """直接通过 URL 进入每个路由，应渲染其签名元素且无 JS 异常。"""
    goto(ui, path)
    assert_no_page_errors(ui)


def test_unknown_route_falls_back_to_home(ui):
    """未知路由应回退到首页（由路由回调兜底）。"""
    goto(ui, "/this-route-does-not-exist")
    ui.wait_for_selector("#first-use-guide", timeout=30000, state="attached")
    assert_no_page_errors(ui)


def test_sidebar_nav_click_routes_client_side(ui):
    """从首页点击侧边栏链接，应客户端路由到对应页。"""
    goto(ui, "/home")
    for key in ["data-center", "strategy-center", "factor-center",
                "backtest-center", "visual-dashboard", "report-center",
                "settings", "market-watch", "home"]:
        click_nav(ui, key)
        assert_no_page_errors(ui)


def test_sidebar_toggle_collapses(ui):
    """移动端汉堡按钮应切换侧边栏开合；桌面端该按钮默认隐藏则跳过。"""
    goto(ui, "/home")
    btn = ui.locator("#sidebar-toggle-btn")
    if btn.count() > 0 and btn.is_visible():
        btn.click()
        assert_no_page_errors(ui)
    else:
        # 桌面视口下 d-md-none 隐藏，属预期，跳过
        import pytest

        pytest.skip("桌面视口下侧边栏切换按钮隐藏（d-md-none），跳过。")
