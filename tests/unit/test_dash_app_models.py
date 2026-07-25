import json
from dataclasses import asdict
import pytest
from fisher.dash_app.services.models import (
    StrategyConfig, WizardState, resolve_ticker,
    TYPE_MAP, STRATEGY_PARAM_SCHEMAS,
)


class TestResolveTicker:
    def test_sh_6_prefix(self):
        assert resolve_ticker("600519") == "600519.SH"

    def test_sh_5_prefix(self):
        assert resolve_ticker("510050") == "510050.SH"

    def test_sz_0_prefix(self):
        assert resolve_ticker("000001") == "000001.SZ"

    def test_sz_3_prefix(self):
        assert resolve_ticker("300750") == "300750.SZ"

    def test_hk_symbol(self):
        assert resolve_ticker("00700", "hk_connect") == "00700.HK"

    def test_bj_prefix(self):
        assert resolve_ticker("830799") == "830799.BJ"

    def test_no_unknown_in_result(self):
        for code in ["600519", "000001", "300750", "00700"]:
            assert "UNKNOWN" not in resolve_ticker(code)


class TestStrategyConfig:
    def test_valid_config_passes(self):
        c = StrategyConfig(name="sma_test", type="sma_cross", params={"fast": 5, "slow": 20})
        assert c.validate() == []

    def test_empty_name_fails(self):
        c = StrategyConfig(name="", type="sma_cross")
        assert len(c.validate()) > 0

    def test_invalid_type_fails(self):
        c = StrategyConfig(name="test", type="nonexistent")
        assert len(c.validate()) > 0

    def test_custom_without_dsl_fails(self):
        c = StrategyConfig(name="test", type="custom")
        assert len(c.validate()) > 0

    def test_safe_filename(self):
        c = StrategyConfig(name="../etc/passwd", type="sma_cross")
        assert "/" not in c.safe_filename
        assert ".." not in c.safe_filename


class TestWizardState:
    def test_default_step_zero(self):
        s = WizardState()
        assert s.step == 0

    def test_serialize_roundtrip(self):
        s = WizardState(step=2, name="test", type="macd", params={"fast": 12})
        d = asdict(s)
        restored = WizardState(**json.loads(json.dumps(d)))
        assert restored.name == "test"
        assert restored.params["fast"] == 12


class TestParamSchemas:
    def test_sma_cross_has_defaults(self):
        s = STRATEGY_PARAM_SCHEMAS["sma_cross"]
        assert s["fast"]["default"] == 5
        assert s["slow"]["default"] == 20

    def test_all_strategies_have_schema(self):
        for type_name in TYPE_MAP:
            assert type_name in STRATEGY_PARAM_SCHEMAS
