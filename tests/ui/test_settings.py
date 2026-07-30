"""系统设置 UI 测试：设置容器与标签页切换。"""
from ui_helpers import assert_no_page_errors, goto


def test_settings_container_present(ui):
    goto(ui, "/settings")
    assert ui.locator("#settings-tabs").count() > 0
    assert_no_page_errors(ui)


def test_settings_tab_switching(ui):
    goto(ui, "/settings")
    ui.get_by_role("tab", name="回测参数").click()
    ui.wait_for_selector("#cfg-capital", timeout=15000)
    ui.get_by_role("tab", name="基准配置").click()
    ui.wait_for_selector("#cfg-benchmark-radio", timeout=15000)
    ui.get_by_role("tab", name="系统日志").click()
    ui.wait_for_selector("#cfg-log-content", timeout=15000)
    assert_no_page_errors(ui)
