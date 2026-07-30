"""Playwright UI 测试公共夹具。

依赖：
- pytest-playwright（已装入项目 .venv）
- 已启动的 FisherQuant 服务（默认 http://127.0.0.1:8050）

运行：
    .venv/Scripts/python -m pytest tests/ui -v
"""
import urllib.request

import pytest


@pytest.fixture(scope="session")
def server_up():
    """若本地服务不可用则跳过整个 UI 测试会话，避免误报失败。"""
    from ui_helpers import BASE_URL

    try:
        with urllib.request.urlopen(BASE_URL + "/", timeout=5) as r:
            if r.status == 200:
                return True
    except Exception:
        pass
    pytest.skip(
        f"FisherQuant 服务在 {BASE_URL} 不可达；请先启动服务（`python run.py`）。"
    )


@pytest.fixture
def browser_context_args():
    """放大视口，避免弹窗（如策略向导）高于默认 1280x720 时被顶部固定头拦截点击。"""
    return {"viewport": {"width": 1600, "height": 1000}}


@pytest.fixture
def ui(page, server_up):
    """增强的 page 夹具：捕获未捕获的 JS 异常与控制台 error。

    通过 `page._captured` 暴露收集到的错误，供断言使用。
    """
    captured = {"pageerrors": [], "console_errors": []}

    def _on_pageerror(exc):
        captured["pageerrors"].append(str(exc))

    def _on_console(msg):
        if msg.type == "error":
            captured["console_errors"].append(f"{msg.type}:{msg.text}")

    page.on("pageerror", _on_pageerror)
    page.on("console", _on_console)
    page.set_default_timeout(30000)
    page._captured = captured
    yield page
