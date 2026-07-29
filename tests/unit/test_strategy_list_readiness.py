"""策略列表「数据就绪」列 + 回测缺失清单渲染单测（AC-4 / T3 / T2）。"""
from fisher.dash_app.callbacks.strategy_crud_callbacks import _build_strategy_list
from fisher.dash_app.callbacks.backtest_callbacks import _render_readiness_manifest
from fisher.dash_app.services.strategy_data_service import ReadinessReport, MissingItem


def _strat(name):
    return {"name": name, "type": "sma_cross", "symbols": ["600519.SH"],
            "params": {}, "enabled": True, "created_at": "2024-01-01 00:00"}


def test_build_list_shows_readiness_column_when_map_provided():
    div = _build_strategy_list([_strat("S1")], {"S1": ("ready", [])})
    txt = str(div)
    assert "数据就绪" in txt
    assert "✓ 可回测" in txt


def test_build_list_ready_backward_compat_without_map():
    div = _build_strategy_list([_strat("S1")])  # readiness_map=None
    assert "数据就绪" in str(div)               # 列头仍渲染
    assert "✓ 可回测" not in str(div)           # 无 map 时不渲染误导性的就绪徽章


def test_build_list_partial_badge():
    div = _build_strategy_list(
        [_strat("S2")],
        {"S2": ("partial", [MissingItem(symbol="600519.SH", types=["adj"])])},
    )
    assert "⚠ 部分缺" in str(div)


def test_build_list_blocked_badge():
    div = _build_strategy_list(
        [_strat("S3")],
        {"S3": ("blocked", [MissingItem(symbol="600519.SH", types=["daily", "adj"])])},
    )
    assert "✗ 全缺" in str(div)


def test_render_readiness_manifest_lists_missing():
    rep = ReadinessReport(
        ready=False, blocking=True,
        missing=[MissingItem(symbol="600519.SH", types=["daily", "adj"])],
        symbols=["600519.SH"],
    )
    div = _render_readiness_manifest(rep)
    txt = str(div)
    assert "600519.SH" in txt
    assert "复权因子" in txt
    assert "日线" in txt
