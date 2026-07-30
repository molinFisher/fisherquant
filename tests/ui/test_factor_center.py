"""因子中心 UI 测试：标签页切换与关键控件。"""
from ui_helpers import assert_no_page_errors, goto


def test_factor_center_key_controls(ui):
    goto(ui, "/factor-center")
    assert ui.locator("#factor-center-tabs").count() > 0
    assert ui.locator("#factor-compute-btn").count() > 0
    assert_no_page_errors(ui)


def test_factor_center_tab_switching(ui):
    goto(ui, "/factor-center")
    ui.get_by_role("tab", name="因子列表").click()
    ui.wait_for_selector("#factor-list-table", timeout=15000)
    ui.get_by_role("tab", name="数据预览").click()
    ui.wait_for_selector("#factor-preview-symbol", timeout=15000)
    assert_no_page_errors(ui)
