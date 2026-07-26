from datetime import datetime
import logging
import polars as pl
from ..event.types import Signal, OrderSide, OrderStatus
from ..oms.orders import create_order
from ..paper.engine import PaperEngine
from ..position.service import PositionService
from .time_player import TimePlayer
from ..portfolio.builder import PortfolioBuilder

logger = logging.getLogger(__name__)


def _date_str(bar_time: float) -> str:
    return datetime.fromtimestamp(bar_time).strftime("%Y-%m-%d")


class BacktestEngine:
    """事件驱动的回测引擎。

    对应量化系统改进清单的关键修正：
    - P0-1：NAV = 现金(available) + 单一持仓账本(PositionService)市值，删除重复记账；
    - P0-2：成交延迟由 PaperEngine 保证（信号 bar N → 成交 bar N+1），本层无向前看；
    - P0-3：滑点由 PaperEngine/FillSimulator 处理；
    - P0-4：每个新交易日开始调用 PositionService.settle_t1() 解冻 T+1；卖出前校验可用持仓；
    - P0-5：下单前用 RiskEngine 预检，每根 bar 记录净值变动用于 DailyLossLimit；
    - P0-6：每根 bar 调用 paper.check_conditions 触发止损/止盈条件单；
    - P2-15：额外跟踪"扣费前"净值（gross_nav）用于成本拖累对比。
    """

    def __init__(
        self,
        bars_df: pl.DataFrame,
        paper_engine: PaperEngine,
        position_service: PositionService,
        portfolio_builder: PortfolioBuilder | None = None,
        risk_engine=None,
        enable_risk: bool = True,
        enable_conditions: bool = True,
        settle_t1_daily: bool = True,
        seed: int | None = None,
    ):
        self._bars_df = bars_df
        self._paper = paper_engine
        self._positions = position_service
        self._portfolio_builder = portfolio_builder or PortfolioBuilder()
        self._risk_engine = risk_engine
        self._enable_risk = enable_risk and risk_engine is not None
        self._enable_conditions = enable_conditions
        self._settle_t1_daily = settle_t1_daily
        self._seed = seed
        self._nav_history: list[float] = []
        self._gross_nav_history: list[float] = []
        self._trades: list[dict] = []
        self._latest_prices: dict[str, float] = {}
        self._cum_commission: float = 0.0
        self._risk_rejections: list[dict] = []

    async def run(self, strategy) -> dict:
        # P2-14：可复现性 —— 固定随机种子
        if self._seed is not None:
            from .repro import set_global_seed
            set_global_seed(self._seed)
        await strategy.on_init()
        player = TimePlayer(self._bars_df)
        account = self._paper.get_account()
        nav0 = account["available"]
        self._nav_history.append(nav0)
        self._gross_nav_history.append(nav0)
        self._trades = []
        self._risk_rejections = []

        prev_date: str | None = None
        prev_nav = nav0

        for bar in player:
            bar_date = _date_str(bar.bar_time)

            # P0-4：新交易日开始解冻 T+1；重置当日风险累计
            if prev_date is not None and bar_date != prev_date:
                if self._settle_t1_daily:
                    self._positions.settle_t1()
                if self._risk_engine is not None:
                    self._risk_engine.reset_daily()
            prev_date = bar_date

            self._latest_prices[bar.ticker] = bar.close

            await strategy.on_bar(bar)
            signals = strategy.on_signal()

            if signals:
                self._process_signals(signals, account["available"])

            filled = self._paper.on_bar(bar)
            for order in filled:
                self._positions.update_on_fill(order, order.filled_price)
                self._cum_commission += order.commission
                self._trades.append({
                    "ticker": order.ticker,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "price": order.filled_price,
                    "commission": order.commission,
                    "timestamp": bar.bar_time,
                    "trade_date": bar_date,
                })

            # P0-6：触发止损/止盈条件单（下一根 bar 成交）
            if self._enable_conditions:
                self._paper.check_conditions(bar.ticker, bar.close)

            self._positions.mark_to_market(self._latest_prices)
            account = self._paper.get_account()

            # P0-1：单一账本 NAV
            nav = account["available"] + sum(
                p["market_value"] for p in self._positions.get_all_positions().values()
            )
            # P2-15：扣费前净值 ≈ 净值 + 累计费用（成本拖累对比）
            gross_nav = nav + self._cum_commission
            self._nav_history.append(nav)
            self._gross_nav_history.append(gross_nav)

            # P0-5：记录净值变动用于日内亏损限额
            if self._risk_engine is not None:
                self._risk_engine.record_pnl(nav - prev_nav)
            prev_nav = nav

        return {
            "nav_history": self._nav_history,
            "gross_nav_history": self._gross_nav_history,
            "trades": self._trades,
            "risk_rejections": self._risk_rejections,
        }

    def _process_signals(self, signals: list[Signal], capital: float) -> None:
        orders = self._portfolio_builder.build_orders(signals, capital)
        for o in orders:
            # P0-4：T+1 —— 卖出前校验可用持仓（已排除当日买入冻结）
            # P1-8：allow_short 时无持仓也允许卖出（开空），跳过可用持仓校验
            if o.side == OrderSide.SELL and not getattr(self._positions, "_allow_short", False):
                pos = self._positions.get_position(o.ticker)
                avail = pos["available"] if pos else 0
                if avail <= 0:
                    continue
                if o.quantity > avail:
                    o.quantity = avail

            # P0-5：下单前风险预检
            if self._enable_risk and self._risk_engine is not None:
                ok, reasons = self._risk_engine.check(o, self._positions, capital, market_price=o.price)
                if not ok:
                    self._risk_rejections.append({
                        "ticker": o.ticker, "side": o.side.value,
                        "reasons": reasons,
                    })
                    logger.info("Risk rejected %s %s: %s", o.side.value, o.ticker, reasons)
                    continue

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
