"""Dash 单元测试脚手架（Phase 3）。

目的：在不启动真实 Dash server（避免 diskcache / Scheduler / network 副作用）的前提下，
直接 import 并调用 13 个回调模块的函数。通过「假 app」捕获 @app.callback / @callback
装饰的闭包，供测试按 Output 组件 id 取回并直接调用。
"""
import sys
import os
from contextlib import contextmanager


class _CallbackRegistry:
    def __init__(self):
        self._by_id = {}
        self._all = []

    def register(self, outputs, func):
        self._all.append(func)
        outs = outputs if isinstance(outputs, (list, tuple)) else [outputs]
        for o in outs:
            cid = getattr(o, "component_id", None) or getattr(o, "id", None)
            if cid is None:
                continue
            self._by_id.setdefault(cid, []).append(func)

    def get(self, component_id):
        funcs = self._by_id.get(component_id)
        if not funcs:
            raise KeyError(f"No callback registered for output id {component_id!r}")
        return funcs[-1]

    def all_callbacks(self):
        return list(self._all)

    def count(self):
        return len(self._all)


class FakeDashApp:
    """捕捉 @app.callback(...) 装饰函数的极简 Dash app 替身。"""

    def __init__(self):
        self._reg = _CallbackRegistry()

    @property
    def callback(self):
        reg = self._reg

        def decorator(*args, **kwargs):
            outputs = args[0] if args else None

            def wrap(func):
                reg.register(outputs, func)
                return func

            return wrap

        return decorator

    def get_callback(self, component_id):
        return self._reg.get(component_id)

    def all_callbacks(self):
        return self._reg.all_callbacks()

    def callback_count(self):
        return self._reg.count()


@contextmanager
def capture_dash_callbacks(app=None):
    """捕获 @app.callback 与裸 @callback（dash.callback）两种写法的注册。

    - 进入上下文前已 import 的 fisher.dash_app 模块，其模块级 `callback` 引用会被临时替换为捕获器；
    - 上下文内新 import 的模块会 `from dash import callback` 拿到被 patch 的 `dash.callback`；
    - `register_all_callbacks(fake_app)` / `register_X_callbacks(fake_app)` 中的 `@app.callback`
      走 FakeDashApp.callback，同样被捕获。
    退出时全部还原。
    """
    import dash

    app = app or FakeDashApp()
    reg = app._reg

    def capturing_decorator(*args, **kwargs):
        outputs = args[0] if args else None

        def wrap(func):
            reg.register(outputs, func)
            return func

        return wrap

    original_dash_callback = getattr(dash, "callback", None)
    dash.callback = capturing_decorator

    patched = []
    for name, mod in list(sys.modules.items()):
        if name.startswith("fisher.dash_app") and hasattr(mod, "callback"):
            patched.append((mod, mod.callback))
            mod.callback = capturing_decorator

    try:
        yield app
    finally:
        dash.callback = original_dash_callback
        for mod, cb in patched:
            mod.callback = cb
