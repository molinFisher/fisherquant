"""首页功能测试（只读，不触发外部网络）。"""
from ui_helpers import assert_no_page_errors, goto


def test_home_stats_render(ui):
    """首页统计卡片应渲染（依赖本地 DuckDB，不直接联网）。"""
    goto(ui, "/home")
    # 首页布局为静态渲染，先等一个稳定存在的元素，再校验各统计卡片存在
    ui.wait_for_selector("#first-use-guide", timeout=30000, state="attached")
    for sel in ["#stat-tickers-count", "#stat-ashare-count",
                "#stat-hk-count", "#stat-records-count",
                "#stat-last-update"]:
        assert ui.locator(sel).count() > 0, f"缺少首页元素 {sel}"
    assert_no_page_errors(ui)


def test_home_quick_actions_present(ui):
    """首页快捷入口按钮应存在。"""
    goto(ui, "/home")
    ui.wait_for_selector("#quick-fetch", timeout=30000, state="attached")
    for sel in ["#quick-fetch", "#quick-strategy", "#quick-backtest"]:
        assert ui.locator(sel).count() > 0, f"缺少快捷按钮 {sel}"
    assert_no_page_errors(ui)


def test_home_first_use_guide_present(ui):
    """首次使用引导区块应渲染。"""
    goto(ui, "/home")
    assert ui.locator("#first-use-guide").count() > 0
    assert_no_page_errors(ui)
