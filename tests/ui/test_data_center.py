"""数据中心页面 UI 测试（结构 + 标签页切换，不触发外部网络）。"""
from ui_helpers import assert_no_page_errors, goto


def test_data_center_key_controls_present(ui):
    goto(ui, "/data-center")
    for sel in ["#data-type-radio", "#candidate-list", "#cache-filter-input",
                "#data-center-tabs"]:
        assert ui.locator(sel).count() > 0, f"缺少元素 {sel}"
    assert_no_page_errors(ui)


def test_data_center_tab_switching(ui):
    goto(ui, "/data-center")
    ui.get_by_role("tab", name="已缓存数据").click()
    ui.wait_for_selector("#cache-delete-btn", timeout=15000)
    ui.get_by_role("tab", name="高级功能").click()
    ui.wait_for_selector("#export-data-btn", timeout=15000)
    ui.get_by_role("tab", name="自动加载").click()
    ui.wait_for_selector("#auto-load-progress-bar", timeout=15000)
    assert_no_page_errors(ui)
