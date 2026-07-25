from datetime import datetime
import polars as pl
from ..event.types import Signal, OrderSide, OrderStatus
from ..oms.orders import create_order
from ..paper.engine import PaperEngine
from ..position.service import PositionService
from .time_player import TimePlayer
from ..portfolio.builder import PortfolioBuilder


class BacktestEngine:
    def __init__(
        self,
        bars_df: pl.DataFrame,
        paper_engine: PaperEngine,
        position_service: PositionService,
        portfolio_builder: PortfolioBuilder | None = None,
    ):
        self._bars_df = bars_df
        self._paper = paper_engine
        self._positions = position_service
        self._portfolio_builder = portfolio_builder or PortfolioBuilder()
        self._nav_history: list[float] = []
        self._trades: list[dict] = []
        self._latest_prices: dict[str, float] = {}

    async def run(self, strategy) -> dict:
        await strategy.on_init()
        player = TimePlayer(self._bars_df)
        account = self._paper.get_account()
        self._nav_history.append(account["capital"])
        self._trades = []

        for bar in player:
            self._latest_prices[bar.ticker] = bar.close

            await strategy.on_bar(bar)
            signals = strategy.on_signal()

            if signals:
                self._process_signals(signals, account["capital"])

            filled = self._paper.on_bar(bar)
            for order in filled:
                self._positions.update_on_fill(order, order.filled_price)
                self._trades.append({
                    "ticker": order.ticker,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "price": order.filled_price,
                    "commission": order.commission,
                    "timestamp": bar.bar_time,
                })

            self._positions.mark_to_market(self._latest_prices)
            account = self._paper.get_account()
            nav = self._compute_nav()
            self._nav_history.append(nav)

        return {
            "nav_history": self._nav_history,
            "trades": self._trades,
        }

    def _process_signals(self, signals: list[Signal], capital: float) -> None:
        orders = self._portfolio_builder.build_orders(signals, capital)
        for o in orders:
            order = create_order(
                ticker=o.ticker,
                market=o.market,
                asset_type="stock",
                side=o.side,
                quantity=max(o.quantity, 1),
                price=o.price,
                order_type=o.order_type,
            )
            self._paper.submit_order(order)

    def _compute_nav(self) -> float:
        account = self._paper.get_account()
        cash = account["capital"]
        positions_value = sum(
            p["market_value"] for p in self._positions.get_all_positions().values()
        )
        return cash + positions_value
