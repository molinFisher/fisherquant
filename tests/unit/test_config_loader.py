import os
import tempfile
from pathlib import Path
from fisher.config.loader import ConfigLoader, ConfigLoadError


class TestConfigLoader:
    def test_loads_defaults_when_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ConfigLoader.load(d)
            assert cfg.system.mode.value == "paper"
            assert cfg.market.source == "akshare"

    def test_overrides_from_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("mode: backtest")
            cfg = ConfigLoader.load(d)
            assert cfg.system.mode.value == "backtest"
            assert cfg.market.source == "akshare"

    def test_env_var_substitution(self):
        os.environ["TEST_REDIS_URL"] = "redis://localhost:6379"
        try:
            with tempfile.TemporaryDirectory() as d:
                Path(d, "system.yaml").write_text(
                    "event:\n  backend: redis\n  redis_url: ${TEST_REDIS_URL}"
                )
                cfg = ConfigLoader.load(d)
                assert cfg.system.event.redis_url == "redis://localhost:6379"
        finally:
            del os.environ["TEST_REDIS_URL"]

    def test_missing_env_var_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("event:\n  redis_url: ${MISSING_VAR}")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass

    def test_merges_fees_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "fees.yaml").write_text("""
assets:
  a_share:
    commission_rate: 0.0001
""")
            cfg = ConfigLoader.load(d)
            assert cfg.fees.assets["a_share"].commission_rate == 0.0001

    def test_invalid_yaml_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text(": invalid yaml :")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass

    def test_invalid_config_values_raises(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "system.yaml").write_text("mode: invalid_mode")
            try:
                ConfigLoader.load(d)
                assert False, "should have raised"
            except ConfigLoadError:
                pass
