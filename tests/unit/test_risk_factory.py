"""强断言测试：fisher/risk/factory.py。

覆盖：
- build_risk_engine 从显式配置 dict 构建引擎，断言规则数量与类型
- build_risk_engine(load_risk_config()) 集成默认 risk.yaml，断言规则数=4、类型齐全
- 空配置 / 无 pre_trade 返回 None
- 未知规则名被跳过（warning，不报错）
- 顶层 blacklist 注入到 BlacklistRule
"""
import pytest

from fisher.risk.factory import build_risk_engine, load_risk_config
from fisher.risk.pre_trade import (
    MaxPositionRule,
    DailyLossLimitRule,
    PriceLimitRule,
    BlacklistRule,
    SectorLimitRule,
)
from fisher.risk.engine import RiskEngine


def _config_with(pre_trade, blacklist=None):
    cfg = {"pre_trade": pre_trade}
    if blacklist is not None:
        cfg["blacklist"] = blacklist
    return cfg


class TestBuildRiskEngineFromConfig:
    def test_rule_count_and_types(self):
        cfg = _config_with([
            {"rule": "MaxPosition", "params": {"max_pct": 0.2}},
            {"rule": "DailyLossLimit", "params": {"max_loss_pct": 0.05}},
            {"rule": "PriceLimit"},
            {"rule": "SectorLimit", "params": {"max_pct": 0.3}},
        ])
        engine = build_risk_engine(cfg)
        assert isinstance(engine, RiskEngine)
        assert len(engine._rules) == 4
        assert any(isinstance(r, MaxPositionRule) for r in engine._rules)
        assert any(isinstance(r, DailyLossLimitRule) for r in engine._rules)
        assert any(isinstance(r, PriceLimitRule) for r in engine._rules)
        assert any(isinstance(r, SectorLimitRule) for r in engine._rules)

    def test_rule_params_applied(self):
        cfg = _config_with([
            {"rule": "MaxPosition", "params": {"max_pct": 0.33}},
        ])
        engine = build_risk_engine(cfg)
        rule = engine._rules[0]
        assert isinstance(rule, MaxPositionRule)
        assert rule._max_pct == 0.33

    def test_unknown_rule_is_skipped(self):
        cfg = _config_with([
            {"rule": "MaxPosition", "params": {"max_pct": 0.2}},
            {"rule": "NoSuchRule"},
        ])
        engine = build_risk_engine(cfg)
        # 未知规则被跳过，仅保留已知规则
        assert len(engine._rules) == 1
        assert isinstance(engine._rules[0], MaxPositionRule)

    def test_blacklist_injected_from_top_level(self):
        cfg = _config_with(
            [{"rule": "Blacklist"}],
            blacklist=["600519.SH", "000001.SZ"],
        )
        engine = build_risk_engine(cfg)
        rule = engine._rules[0]
        assert isinstance(rule, BlacklistRule)
        assert rule._blacklist == {"600519.SH", "000001.SZ"}

    def test_blacklist_explicit_params_take_precedence(self):
        cfg = _config_with(
            [{"rule": "Blacklist", "params": {"blacklist": ["000002.SZ"]}}],
            blacklist=["600519.SH"],
        )
        engine = build_risk_engine(cfg)
        rule = engine._rules[0]
        assert rule._blacklist == {"000002.SZ"}

    def test_empty_config_returns_none(self):
        assert build_risk_engine(None) is None
        assert build_risk_engine({}) is None

    def test_no_pre_trade_returns_none(self):
        assert build_risk_engine({"realtime": {"beta_limit": 1.5}}) is None

    def test_all_unknown_rules_returns_none(self):
        cfg = _config_with([{"rule": "Gibberish"}])
        assert build_risk_engine(cfg) is None


class TestBuildRiskEngineWithDefaultConfig:
    def test_load_risk_config_returns_mapping(self):
        cfg = load_risk_config()
        # 默认 configs/risk.yaml 存在且含 pre_trade
        assert cfg is not None
        assert "pre_trade" in cfg

    def test_default_config_builds_four_rules(self):
        cfg = load_risk_config()
        engine = build_risk_engine(cfg)
        assert isinstance(engine, RiskEngine)
        # 《测试计划》预期：默认配置应返回 4 条 pre_trade 规则
        assert len(engine._rules) == 4
        seen = {type(r).__name__ for r in engine._rules}
        assert "MaxPositionRule" in seen
        assert "DailyLossLimitRule" in seen
        assert "PriceLimitRule" in seen
        assert "SectorLimitRule" in seen

    def test_default_rules_are_distinct_instances(self):
        cfg = load_risk_config()
        engine = build_risk_engine(cfg)
        # 四条规则应为不同实例
        assert len({id(r) for r in engine._rules}) == 4
