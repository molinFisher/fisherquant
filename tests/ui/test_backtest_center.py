"""回测中心 UI 测试：表单控件与多标签页切换。"""
from ui_helpers import assert_no_page_errors, goto


def test_backtest_single_form_present(ui):
    goto(ui, "/backtest-center")
    for sel in ["#bt-run-btn", "#bt-capital", "#bt-commission",
                "#bt-date-range", "#bt-benchmark", "#backtest-tabs"]:
        assert ui.locator(sel).count() > 0, f"缺少元素 {sel}"
    assert_no_page_errors(ui)


def test_backtest_tabs_switch(ui):
    goto(ui, "/backtest-center")
    ui.get_by_role("tab", name="多策略对比").click()
    ui.wait_for_selector("#bt-multi-run-btn", timeout=15000)
    ui.get_by_role("tab", name="滚动优化").click()
    ui.wait_for_timeout(500)
    ui.get_by_role("tab", name="参数敏感性").click()
    ui.wait_for_timeout(500)
    ui.get_by_role("tab", name="市场环境").click()
    ui.wait_for_selector("#bt-regime-run-btn", timeout=15000)
    ui.get_by_role("tab", name="回测历史").click()
    ui.wait_for_selector("#bt-history-table", timeout=15000)
    assert_no_page_errors(ui)
