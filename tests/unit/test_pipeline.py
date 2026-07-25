import tempfile
import os
import pytest
from fisher.strategy.pipeline import (
    parse_pipeline_yaml,
    build_strategy_from_pipeline,
    PipelineConfig,
    PipelineModelConfig,
    PipelinePortfolioConfig,
)


VALID_YAML = """
pipeline:
  universe: csi300
  lookback: 252d
  factors: [momentum_20d, volatility_60d]
  model:
    type: linear
    weights: [0.6, 0.4]
  portfolio:
    top_k: 30
    method: equal_weight
"""

MINIMAL_YAML = """
pipeline:
  factors: [momentum_20d]
"""

MISSING_PIPELINE_KEY_YAML = """
something_else: {}
"""


class TestPipelineYamlParser:
    def test_parse_valid_yaml(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(VALID_YAML)
            tmp = f.name

        try:
            config = parse_pipeline_yaml(tmp)
            assert config.universe == "csi300"
            assert config.lookback == "252d"
            assert config.factors == ["momentum_20d", "volatility_60d"]
            assert config.model.type == "linear"
            assert config.model.weights == [0.6, 0.4]
            assert config.portfolio.top_k == 30
            assert config.portfolio.method == "equal_weight"
        finally:
            os.unlink(tmp)

    def test_parse_minimal_yaml(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(MINIMAL_YAML)
            tmp = f.name

        try:
            config = parse_pipeline_yaml(tmp)
            assert config.universe == ""
            assert config.lookback == "252d"
            assert config.factors == ["momentum_20d"]
            assert config.model.type == "linear"
            assert config.model.weights == []
            assert config.portfolio.top_k == 30
            assert config.portfolio.method == "equal_weight"
        finally:
            os.unlink(tmp)

    def test_missing_pipeline_key_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(MISSING_PIPELINE_KEY_YAML)
            tmp = f.name

        try:
            with pytest.raises(ValueError, match="pipeline"):
                parse_pipeline_yaml(tmp)
        finally:
            os.unlink(tmp)

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_pipeline_yaml("/nonexistent/path.yaml")


class TestPipelineConfig:
    def test_default_config(self):
        config = PipelineConfig()
        assert config.universe == ""
        assert config.lookback == "252d"
        assert config.factors == []
        assert isinstance(config.model, PipelineModelConfig)
        assert isinstance(config.portfolio, PipelinePortfolioConfig)

    def test_custom_config(self):
        config = PipelineConfig(
            universe="csi500",
            lookback="60d",
            factors=["momentum_20d"],
            model=PipelineModelConfig(type="nonlinear", weights=[1.0]),
            portfolio=PipelinePortfolioConfig(top_k=10, method="risk_parity"),
        )
        assert config.portfolio.top_k == 10
        assert config.portfolio.method == "risk_parity"
        assert config.model.type == "nonlinear"


class TestBuildStrategy:
    def test_build_strategy_from_config(self):
        config = PipelineConfig(
            universe="csi300",
            factors=["momentum_20d"],
            portfolio=PipelinePortfolioConfig(top_k=10, method="equal_weight"),
        )
        strategy = build_strategy_from_pipeline(config)
        assert strategy.name == "alpha_model"
        assert strategy.params["top_n"] == 10
        assert strategy.params["factor_names"] == ["momentum_20d"]
        assert strategy.params["universe"] == "csi300"
