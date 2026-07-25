import json
import tempfile
from pathlib import Path
import pytest
from fisher.dash_app.services.strategy_service import StrategyService
from fisher.dash_app.services.models import StrategyConfig


@pytest.fixture
def strategy_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def service(strategy_dir):
    return StrategyService(strategy_dir)


class TestStrategyCRUD:
    def test_list_empty(self, service):
        assert service.list_strategies() == []

    def test_save_and_list(self, service):
        cfg = StrategyConfig(name="test_sma", type="sma_cross", params={"fast": 5, "slow": 20})
        result = service.save_strategy(cfg)
        assert result["status"] == "ok"
        strategies = service.list_strategies()
        assert len(strategies) == 1
        assert strategies[0]["name"] == "test_sma"

    def test_get_strategy(self, service):
        cfg = StrategyConfig(name="test_sma", type="sma_cross")
        service.save_strategy(cfg)
        data = service.get_strategy("test_sma")
        assert data is not None
        assert data["type"] == "sma_cross"

    def test_get_nonexistent(self, service):
        data = service.get_strategy("nonexistent")
        assert data is None

    def test_delete_strategy(self, service):
        cfg = StrategyConfig(name="test_sma", type="sma_cross")
        service.save_strategy(cfg)
        assert service.delete_strategy("test_sma") is True
        assert service.get_strategy("test_sma") is None

    def test_delete_nonexistent(self, service):
        assert service.delete_strategy("nonexistent") is False

    def test_save_invalid_fails(self, service):
        cfg = StrategyConfig(name="", type="sma_cross")
        result = service.save_strategy(cfg)
        assert result["status"] == "error"

    def test_save_update_existing(self, service):
        cfg1 = StrategyConfig(name="test", type="sma_cross", params={"fast": 5})
        service.save_strategy(cfg1)
        cfg2 = StrategyConfig(name="test", type="sma_cross", params={"fast": 10})
        result = service.save_strategy(cfg2)
        assert result["status"] == "ok"
        data = service.get_strategy("test")
        assert data["params"]["fast"] == 10

    def test_toggle_enabled(self, service):
        cfg = StrategyConfig(name="test", type="sma_cross", enabled=True)
        service.save_strategy(cfg)
        result = service.toggle_enabled("test")
        assert result["enabled"] is False
        result2 = service.toggle_enabled("test")
        assert result2["enabled"] is True

    def test_toggle_nonexistent(self, service):
        result = service.toggle_enabled("nonexistent")
        assert result is None


class TestStrategyImportExport:
    def test_export_json(self, service):
        cfg = StrategyConfig(name="test", type="sma_cross")
        service.save_strategy(cfg)
        exported = service.export_json("test")
        assert exported is not None
        data = json.loads(exported)
        assert data["name"] == "test"
        assert data["type"] == "sma_cross"

    def test_export_nonexistent(self, service):
        exported = service.export_json("nonexistent")
        assert exported is None

    def test_import_json(self, service):
        json_str = json.dumps({
            "name": "imported",
            "type": "sma_cross",
            "params": {"fast": 5, "slow": 20},
        }, ensure_ascii=False)
        result = service.import_json(json_str)
        assert result["status"] == "ok"
        data = service.get_strategy("imported")
        assert data["params"]["fast"] == 5

    def test_import_invalid_json(self, service):
        result = service.import_json("not valid json")
        assert result["status"] == "error"

    def test_import_missing_name(self, service):
        json_str = json.dumps({"type": "sma_cross"})
        result = service.import_json(json_str)
        assert result["status"] == "error"


class TestStrategySanitizedFilenames:
    def test_special_chars(self, service):
        cfg = StrategyConfig(name="../etc/passwd", type="sma_cross")
        result = service.save_strategy(cfg)
        assert result["status"] == "ok"
        data = service.get_strategy("../etc/passwd")
        assert data is not None

    def test_chinese_name(self, service):
        cfg = StrategyConfig(name="测试策略", type="macd")
        service.save_strategy(cfg)
        strategies = service.list_strategies()
        assert any(s["name"] == "测试策略" for s in strategies)
