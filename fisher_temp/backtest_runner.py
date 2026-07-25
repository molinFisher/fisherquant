import polars as pl
from pathlib import Path
from datetime import date
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
from fisher.store.repository import BarRepo
from fisher.backtest.engine import BacktestEngine
from fisher.backtest.time_player import TimePlayer
from fisher.paper.engine import PaperEngine
from fisher.paper.fees import FeeCalculator
from fisher.paper.fill import FillSimulator
from fisher.oms.engine import OMSEngine
from fisher.position.service import PositionService
from fisher.strategy.base import Strategy
from fisher.strategy.registry import StrategyRegistry
from fisher.strategy.engine import StrategyEngine
from fisher.strategy.builtin.momentum import MomentumStrategy
from fisher.portfolio.builder import PortfolioBuilder
from fisher.risk.engine import RiskEngine
from fisher.analytics.performance import compute_performance
from fisher.analytics.report import report_to_html, report_to_json
from fisher.config.schemas import FeesConfig
from fisher.market.rules import get_rules
import json

logger = __import__("logging").getLogger(__name__)


class BacktestRunner:
    def __init__(self, db_path: str):
        self.engine = DuckDBEngine(db_path)
        init_schema(self.engine)

    def run_a_share_backtest(self, tickers: list[str], params: dict) -> dict:
        bars = BarRepo.get_bars_daily(
            self.engine, tickers, params["start"], params["end"]
        )
        if bars.is_empty():
            return {"status": "no_data", "tickers": tickers}

        time_player = TimePlayer(bars)
        strategy_engine = StrategyEngine()
        for t in tickers:
            s = MomentumStrategy({
                "fast_window": params.get("fast", 10),
                "slow_window": params.get("slow", 30),
                "ticker": t,
                "market": "a_share",
            })
            strategy_engine._strategies[f"momentum_{t}"] = s

        rules = get_rules("a_share")
        fees = FeeCalculator(FeesConfig())
        fill = FillSimulator(rules, fill_price_mode="next_open")
        oms = OMSEngine()
        paper = PaperEngine(rules=rules, fees=fees, fill_sim=fill, oms=oms)
        position = PositionService()
        portfolio = PortfolioBuilder(method="equal_weight")
        risk = RiskEngine(FeesConfig().assets.get("a_share"), position)

        nav_series = [params.get("capital", 1000000.0)]
        orders_history = []

        for bar_idx, bar_dict_list in self._iter_bars_by_date(time_player):
            if not bar_dict_list:
                continue
            for bar_dict in bar_dict_list:
                await strategy_engine.on_bar(bar_dict)

            signals = strategy_engine.collect_signals()
            orders = portfolio.build_orders(signals, nav_series[-1])

            for order in orders:
                approved, reason = risk.check(order)
                if approved:
                    oms.submit(order)
                    result = paper.submit_order(order)
                    if result and result.filled_qty > 0:
                        position.update_on_fill(result)
                        nav_series.append(nav_series[-1] + result.filled_qty * result.filled_price)
                        orders_history.append(result)

        metrics = compute_performance(nav_series, [nav_series[0]] * len(nav_series))
        return {
            "status": "success",
            "tickers": tickers,
            "nav_series": nav_series,
            "metrics": metrics,
            "total_orders": len(orders_history),
            "final_nav": nav_series[-1],
        }

    def _iter_bars_by_date(self, player):
        for bars in player:
            yield bars

    def run_hk_backtest(self, tickers: list[str], params: dict) -> dict:
        bars = BarRepo.get_bars_daily(
            self.engine, tickers, params["start"], params["end"]
        )
        if bars.is_empty():
            return {"status": "no_data", "tickers": tickers}
        return self.run_a_share_backtest(tickers, params)
