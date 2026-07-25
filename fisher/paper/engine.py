from ..broker.adapter import BrokerAdapter
from ..event.types import Bar, OrderSide, OrderStatus
from ..oms.orders import Order
from ..oms.engine import OMSEngine
from ..market.rules import ExchangeRules
from ..config.schemas import AssetFeeConfig, FeesConfig
from .fees import FeeCalculator
from .fill import FillSimulator


class PaperEngine(BrokerAdapter):
    def __init__(
        self,
        fee_config: AssetFeeConfig | FeesConfig | None = None,
        rules: ExchangeRules | None = None,
        initial_capital: float = 1_000_000.0,
        fill_price_mode: str = "current_close",
    ):
        self._capital = initial_capital
        self._available = initial_capital
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, dict] = {}
        self._rules = rules
        self._oms = OMSEngine()

        if isinstance(fee_config, FeesConfig):
            self._fee_calc = FeeCalculator.from_config(fee_config)
        elif isinstance(fee_config, AssetFeeConfig):
            self._fee_calc = FeeCalculator({"default": fee_config})
        else:
            self._fee_calc = None

        self._fill_sim = FillSimulator(fill_price_mode=fill_price_mode)

    def submit_order(self, order: Order) -> Order:
        if order.order_id in self._orders:
            raise ValueError(f"Order {order.order_id} already submitted")
        self._oms.submit(order)
        self._orders[order.order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.is_terminal:
            return False
        self._oms.cancel(order_id)
        return True

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_positions(self) -> dict[str, dict]:
        return dict(self._positions)

    def get_account(self) -> dict:
        return {"capital": self._capital, "available": self._available}

    def on_bar(self, bar: Bar) -> list[Order]:
        filled_orders: list[Order] = []

        for order in list(self._orders.values()):
            if order.is_terminal:
                continue
            if order.ticker != bar.ticker:
                continue

            fill_result, fill_price = self._fill_sim.check_fill(order, bar)
            if not fill_result:
                continue

            trade_value = fill_price * order.quantity

            if self._fee_calc is not None:
                try:
                    fees = self._fee_calc.calculate(order.market, order.side, trade_value, order.quantity)
                except ValueError:
                    fees = self._fee_calc.calculate("default", order.side, trade_value, order.quantity)
                commission = fees["total"]
            else:
                commission = 0.0

            self._oms.update_fill(order.order_id, order.quantity, fill_price, commission)

            ticker = order.ticker
            if ticker not in self._positions:
                self._positions[ticker] = {
                    "ticker": ticker,
                    "quantity": 0,
                    "avg_cost": 0.0,
                    "market_value": 0.0,
                }

            pos = self._positions[ticker]
            if order.side.value == "buy":
                total_qty = pos["quantity"] + order.quantity
                total_cost = pos["avg_cost"] * pos["quantity"] + trade_value + commission
                pos["quantity"] = total_qty
                pos["avg_cost"] = total_cost / total_qty if total_qty > 0 else 0.0
            else:
                pos["quantity"] -= order.quantity
                if pos["quantity"] <= 0:
                    pos["quantity"] = 0
                    pos["avg_cost"] = 0.0

            pos["market_value"] = pos["quantity"] * bar.close

            self._available -= trade_value + commission if order.side.value == "buy" else 0
            self._available += trade_value - commission if order.side.value == "sell" else 0

            self._capital = self._available + sum(
                p["market_value"] for p in self._positions.values()
            )

            filled_orders.append(order)

        return filled_orders
