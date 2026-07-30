"""可视化看板 UI 测试：看板容器与图表标签页（图表需先选择回测才可见）。"""
from ui_helpers import assert_no_page_errors, goto


def test_visual_dashboard_container(ui):
    goto(ui, "/visual-dashboard")
    assert ui.locator("#viz-content").count() > 0
    assert ui.locator("#viz-tabs").count() > 0
    assert_no_page_errors(ui)


def test_visual_dashboard_tabs_present(ui):
    """图表标签页在选中回测前处于隐藏，但标签（文本）应存在于 DOM。"""
    goto(ui, "/visual-dashboard")
    for name in ["净值曲线", "回撤分析", "月度热力图", "收益分布", "交易记录", "K线图"]:
        # 标签默认隐藏（需先选回测），用文本匹配而非 ARIA role（role 会忽略隐藏元素）
        assert ui.locator("#viz-tabs a.nav-link", has_text=name).count() > 0, \
            f"缺少图表标签 {name}"
    assert_no_page_errors(ui)
