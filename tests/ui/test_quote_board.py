"""行情看板 UI 测试：自选表、分钟/日线标签页、添加标的弹窗。"""
from ui_helpers import assert_no_page_errors, goto


def test_quote_board_table_present(ui):
    goto(ui, "/market-watch")
    assert ui.locator("#qb-table-container").count() > 0
    assert ui.locator("#qb-add-btn").count() > 0
    assert_no_page_errors(ui)


def test_quote_board_tab_switching(ui):
    """点击分钟线/日线标签应触发切换回调且不抛 JS 异常（图表内容随自选标的而定）。"""
    goto(ui, "/market-watch")
    ui.get_by_role("tab", name="分钟线").click()
    ui.wait_for_timeout(800)
    ui.get_by_role("tab", name="日线").click()
    ui.wait_for_timeout(800)
    assert_no_page_errors(ui)


def test_quote_board_add_symbol_modal(ui):
    goto(ui, "/market-watch")
    ui.click("#qb-add-btn")
    ui.wait_for_selector("#qb-add-symbol-dropdown", timeout=15000)
    assert_no_page_errors(ui)
