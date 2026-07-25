from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class PipelineModelConfig:
    type: str = "linear"
    weights: list[float] = field(default_factory=list)


@dataclass
class PipelinePortfolioConfig:
    top_k: int = 30
    method: str = "equal_weight"


@dataclass
class PipelineConfig:
    universe: str = ""
    lookback: str = "252d"
    factors: list[str] = field(default_factory=list)
    model: PipelineModelConfig = field(default_factory=PipelineModelConfig)
    portfolio: PipelinePortfolioConfig = field(default_factory=PipelinePortfolioConfig)


def parse_pipeline_yaml(path: str | Path) -> PipelineConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Pipeline YAML not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or "pipeline" not in raw:
        raise ValueError("YAML must contain a top-level 'pipeline' key")

    p = raw["pipeline"]
    model_raw = p.get("model", {})
    portfolio_raw = p.get("portfolio", {})

    return PipelineConfig(
        universe=p.get("universe", ""),
        lookback=p.get("lookback", "252d"),
        factors=p.get("factors", []),
        model=PipelineModelConfig(
            type=model_raw.get("type", "linear"),
            weights=model_raw.get("weights", []),
        ),
        portfolio=PipelinePortfolioConfig(
            top_k=portfolio_raw.get("top_k", 30),
            method=portfolio_raw.get("method", "equal_weight"),
        ),
    )


def build_strategy_from_pipeline(config: PipelineConfig):
    # Runtime import to avoid circular dependency (pipeline -> strategy.builtin -> pipeline)
    from ..strategy.builtin.alpha_model import AlphaModelStrategy

    return AlphaModelStrategy({
        "top_n": config.portfolio.top_k,
        "factor_names": config.factors,
        "model_type": config.model.type,
        "model_weights": config.model.weights,
        "universe": config.universe,
    })
