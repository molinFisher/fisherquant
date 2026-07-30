"""报告中心 UI 测试：报告表单与预览控件。"""
from ui_helpers import assert_no_page_errors, goto


def test_report_center_form_present(ui):
    goto(ui, "/report-center")
    for sel in ["#report-generate-btn", "#report-format-radio",
                "#report-preview-iframe", "#report-sections-checklist",
                "#report-backtest-id-input"]:
        assert ui.locator(sel).count() > 0, f"缺少元素 {sel}"
    assert_no_page_errors(ui)
