"""UI 测试辅助：基础 URL、路由签名、导航与错误断言。"""
from __future__ import annotations

BASE_URL = "http://127.0.0.1:8050"

# 每个路由加载后应出现的关键签名元素（用于等待渲染完成，
# 同时能捕获「回调失败导致元素未渲染」这类真实 bug）。
PAGE_SIGNATURE = {
    "/home": "#first-use-guide",
    "/data-center": "#data-center-content",
    "/market-watch": "#qb-table-container",
    "/strategy-center": "#strategy-table-container",
    "/factor-center": "#factor-center-tabs",
    "/backtest-center": "#bt-run-btn",
    "/visual-dashboard": "#viz-content",
    "/report-center": "#report-generate-btn",
    "/settings": "#settings-tabs",
}

# 侧边栏导航链接的 href（点击触发客户端路由）
NAV_HREF = {
    "home": "/home",
    "data-center": "/data-center",
    "market-watch": "/market-watch",
    "strategy-center": "/strategy-center",
    "factor-center": "/factor-center",
    "backtest-center": "/backtest-center",
    "visual-dashboard": "/visual-dashboard",
    "report-center": "/report-center",
    "settings": "/settings",
}


# 首页统计卡片为静态布局（初始 "0"），可作为「页面已渲染」的稳定标志
HOME_READY = "#first-use-guide"


def goto(ui, path: str, timeout: int = 30000):
    """直接通过 URL 进入某路由，并等待其签名元素出现。

    使用 domcontentloaded + attached，避免等待整页资源（含 Dash 资产）
    在负载较高的实时服务上偶发超时。
    """
    marker = PAGE_SIGNATURE.get(path, HOME_READY)
    ui.goto(BASE_URL + path, wait_until="domcontentloaded")
    ui.wait_for_selector(marker, timeout=timeout, state="attached")


def click_nav(ui, nav_key: str):
    """点击侧边栏导航链接（客户端路由），并等待目标页签名元素。"""
    href = NAV_HREF[nav_key]
    ui.click(f'a[href="{href}"]')
    marker = PAGE_SIGNATURE.get(href, "#page-content")
    ui.wait_for_selector(marker, timeout=20000, state="attached")


def assert_no_page_errors(ui):
    """断言没有出现未捕获的 JS 异常。"""
    errs = getattr(ui, "_captured", {}).get("pageerrors", [])
    assert not errs, f"页面出现未捕获 JS 异常: {errs}"


def assert_no_console_errors(ui):
    """断言控制台没有 error 级日志（不含 benign 警告）。"""
    errs = getattr(ui, "_captured", {}).get("console_errors", [])
    assert not errs, f"控制台出现 error 日志: {errs}"


def close_wizard(ui):
    """确保策略向导弹窗已关闭（优先用 Esc，避免点击被淡入动画遮罩拦截）。"""
    modal = ui.locator("#strategy-wizard-modal")
    if modal.count() > 0 and modal.is_visible():
        # 先等淡入完成，避免遮挡
        try:
            ui.wait_for_function(
                "() => { const m = document.querySelector('#strategy-wizard-modal');"
                " const w = m && m.closest('.modal');"
                " return !!(w && w.classList.contains('show')); }",
                timeout=5000,
            )
        except Exception:
            pass
        ui.keyboard.press("Escape")
        try:
            ui.wait_for_selector("#strategy-wizard-modal", timeout=10000, state="hidden")
        except Exception:
            cancel = ui.locator("#wizard-cancel-btn")
            if cancel.count() > 0 and cancel.is_visible():
                cancel.click()
            ui.wait_for_selector("#strategy-wizard-modal", timeout=5000, state="hidden")


def open_wizard(ui):
    """打开策略向导弹窗（带重试：偶发点击丢失则重试点开）。"""
    for _ in range(4):
        if (ui.locator("#wizard-name").count() > 0
                and ui.locator("#wizard-name").is_visible()):
            break
        close_wizard(ui)
        ui.locator("#strategy-create-btn").wait_for(state="visible", timeout=5000)
        ui.click("#strategy-create-btn")
        try:
            ui.wait_for_selector("#wizard-name", timeout=6000, state="visible")
            break
        except Exception:
            continue
    ui.wait_for_selector("#wizard-name", timeout=20000, state="visible")
    # 等待 Bootstrap 淡入动画完成（外层 .modal 增加 .show 类），
    # 否则弹窗内按钮点击可能被遮罩/头部拦截
    ui.wait_for_function(
        "() => { const m = document.querySelector('#strategy-wizard-modal');"
        " const w = m && m.closest('.modal');"
        " return !!(w && w.classList.contains('show')); }",
        timeout=5000,
    )
