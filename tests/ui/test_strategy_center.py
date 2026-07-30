"""策略中心 UI 测试：列表渲染、新建向导打开、步骤推进与模板联动。"""
from ui_helpers import assert_no_page_errors, close_wizard, goto, open_wizard


def test_strategy_table_renders(ui):
    goto(ui, "/strategy-center")
    assert ui.locator("#strategy-table-container").count() > 0
    assert ui.locator("#strategy-create-btn").count() > 0
    assert_no_page_errors(ui)


def test_open_wizard_basic_fields(ui):
    goto(ui, "/strategy-center")
    open_wizard(ui)
    # 向导打开后，步骤1基础字段（名称/类型/描述）应可见
    assert ui.locator("#wizard-type").count() > 0
    assert ui.locator("#wizard-description").count() > 0
    # 步骤1页脚应含「下一步」「取消」
    assert ui.locator("#wizard-next-btn").count() > 0
    assert ui.locator("#wizard-cancel-btn").count() > 0
    assert_no_page_errors(ui)
    close_wizard(ui)


def test_wizard_advance_and_templates(ui):
    """进入步骤2（参数配置）后，模板按钮应出现，推进过程不抛 JS 异常。"""
    goto(ui, "/strategy-center")
    open_wizard(ui)
    ui.click("#wizard-next-btn")
    # 步骤2：参数配置（含因子模板）应渲染
    ui.wait_for_selector("#template-sma", timeout=15000, state="visible")
    # 模板按钮可见即说明已推进到「参数配置」步骤
    assert ui.locator("#template-sma").count() > 0
    assert_no_page_errors(ui)
    close_wizard(ui)


def test_wizard_cancel_closes_modal(ui):
    goto(ui, "/strategy-center")
    open_wizard(ui)
    ui.click("#wizard-cancel-btn")
    ui.wait_for_selector("#strategy-wizard-modal", timeout=10000, state="hidden")
    assert_no_page_errors(ui)
