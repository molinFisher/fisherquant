import pytest
import json
from fisher.analytics.attribution import brinson_attribution
from fisher.analytics.report import report_to_json, report_to_html


class TestBrinsonAttribution:
    def test_simple_attribution(self):
        portfolio = {
            "Tech": {"weight": 0.6, "return": 0.15},
            "Finance": {"weight": 0.4, "return": 0.05},
        }
        benchmark = {
            "Tech": {"weight": 0.5, "return": 0.15},
            "Finance": {"weight": 0.5, "return": 0.05},
        }
        result = brinson_attribution(portfolio, benchmark)
        assert "total_excess_return" in result
        assert "allocation_effect" in result
        assert "selection_effect" in result
        assert "interaction_effect" in result

    def test_identical_weights_zero_attribution(self):
        portfolio = {
            "Tech": {"weight": 0.5, "return": 0.10},
            "Finance": {"weight": 0.5, "return": 0.05},
        }
        benchmark = {
            "Tech": {"weight": 0.5, "return": 0.10},
            "Finance": {"weight": 0.5, "return": 0.05},
        }
        result = brinson_attribution(portfolio, benchmark)
        assert result["allocation_effect"] == pytest.approx(0.0, abs=1e-6)
        assert result["selection_effect"] == pytest.approx(0.0, abs=1e-6)
        assert result["interaction_effect"] == pytest.approx(0.0, abs=1e-6)
        assert result["total_excess_return"] == pytest.approx(0.0, abs=1e-6)

    def test_overweight_winning_sector(self):
        portfolio = {
            "A": {"weight": 0.8, "return": 0.20},
            "B": {"weight": 0.2, "return": 0.10},
        }
        benchmark = {
            "A": {"weight": 0.5, "return": 0.20},
            "B": {"weight": 0.5, "return": 0.10},
        }
        result = brinson_attribution(portfolio, benchmark)
        assert result["allocation_effect"] > 0

    def test_per_sector_details(self):
        portfolio = {
            "Tech": {"weight": 0.6, "return": 0.15},
            "Finance": {"weight": 0.4, "return": 0.05},
        }
        benchmark = {
            "Tech": {"weight": 0.4, "return": 0.15},
            "Finance": {"weight": 0.6, "return": 0.05},
        }
        result = brinson_attribution(portfolio, benchmark)
        assert "sectors" in result
        assert "Tech" in result["sectors"]
        assert "Finance" in result["sectors"]

    def test_empty_input(self):
        result = brinson_attribution({}, {})
        assert result["total_excess_return"] == 0.0


class TestReporting:
    def test_report_to_json(self):
        metrics = {
            "cumulative_return": 0.15,
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.08,
        }
        json_str = report_to_json(metrics)
        data = json.loads(json_str)
        assert data["metrics"]["cumulative_return"] == 0.15
        assert data["metrics"]["sharpe_ratio"] == 1.5

    def test_report_to_json_with_attribution(self):
        metrics = {"cumulative_return": 0.15}
        attribution = {"total_excess_return": 0.02}
        json_str = report_to_json(metrics, attribution)
        data = json.loads(json_str)
        assert "attribution" in data

    def test_report_to_html(self):
        metrics = {
            "cumulative_return": 0.15,
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.08,
        }
        html = report_to_html(metrics)
        assert "<!DOCTYPE html>" in html or "<html" in html
        assert "0.15" in html
        assert "1.5" in html
        assert "0.08" in html

    def test_report_to_html_with_attribution(self):
        metrics = {"cumulative_return": 0.15}
        attribution = {"total_excess_return": 0.02}
        html = report_to_html(metrics, attribution)
        assert "Excess Return" in html
