from ..event.types import OrderSide
from ..oms.orders import Order


class PositionService:
    def __init__(self, hkd_cny_rate: float = 0.92):
        self._positions: dict[str, dict] = {}
        self._hkd_cny_rate = hkd_cny_rate
        self._t1_pending: dict[str, list[tuple[int, str]]] = {}

    def update_on_fill(self, order: Order, fill_price: float) -> None:
        ticker = order.ticker
        trade_value = fill_price * order.filled_qty
        commission = order.commission
        is_buy = order.side == OrderSide.BUY

        if ticker not in self._positions:
            self._positions[ticker] = {
                "ticker": ticker,
                "market": order.market,
                "asset_type": order.asset_type,
                "quantity": 0,
                "avg_cost": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "frozen": 0,
                "available": 0,
                "cost_cny": 0.0,
            }

        pos = self._positions[ticker]

        if is_buy:
            total_qty = pos["quantity"] + order.filled_qty
            total_cost = pos["avg_cost"] * pos["quantity"] + trade_value + commission
            pos["quantity"] = total_qty
            pos["avg_cost"] = round(total_cost / total_qty, 4) if total_qty > 0 else 0.0
        else:
            pos["quantity"] -= order.filled_qty
            if pos["quantity"] <= 0:
                self._positions.pop(ticker)
                self._t1_pending.pop(ticker, None)
                return

        if order.market == "a_share" and is_buy:
            if ticker not in self._t1_pending:
                self._t1_pending[ticker] = []
            self._t1_pending[ticker].append((order.filled_qty, "buy"))

        self._update_cost_cny(ticker)
        self._update_available(ticker)

    def get_position(self, ticker: str) -> dict | None:
        return self._positions.get(ticker)

    def get_all_positions(self) -> dict[str, dict]:
        return dict(self._positions)

    def mark_to_market(self, prices: dict[str, float]) -> None:
        for ticker, price in prices.items():
            pos = self._positions.get(ticker)
            if pos is None:
                continue
            pos["market_value"] = round(pos["quantity"] * price, 2)
            pos["unrealized_pnl"] = round(
                pos["market_value"] - pos["avg_cost"] * pos["quantity"], 2
            )

    def freeze(self, ticker: str, quantity: int) -> None:
        pos = self._get_position_or_raise(ticker)
        if quantity > pos["available"]:
            raise ValueError(
                f"Cannot freeze {quantity} shares of {ticker}: insufficient available"
            )
        pos["frozen"] += quantity
        self._update_available(ticker)

    def unfreeze(self, ticker: str, quantity: int) -> None:
        pos = self._get_position_or_raise(ticker)
        pos["frozen"] = max(0, pos["frozen"] - quantity)
        self._update_available(ticker)

    def settle_t1(self) -> None:
        self._t1_pending.clear()
        for ticker in self._positions:
            self._update_available(ticker)

    def snapshot(self) -> list[dict]:
        return [
            {
                "ticker": p["ticker"],
                "market": p["market"],
                "asset_type": p["asset_type"],
                "quantity": p["quantity"],
                "avg_cost": p["avg_cost"],
                "market_value": p["market_value"],
                "unrealized_pnl": p["unrealized_pnl"],
                "frozen": p["frozen"],
                "available": p["available"],
            }
            for p in self._positions.values()
        ]

    def _update_cost_cny(self, ticker: str) -> None:
        pos = self._positions[ticker]
        if pos["market"] == "hk_connect":
            pos["cost_cny"] = round(pos["avg_cost"] * pos["quantity"] * self._hkd_cny_rate, 2)
        else:
            pos["cost_cny"] = round(pos["avg_cost"] * pos["quantity"], 2)

    def _update_available(self, ticker: str) -> None:
        pos = self._positions[ticker]
        total = pos["quantity"]
        frozen = pos["frozen"]

        if pos["market"] == "a_share":
            t1_blocked = sum(qty for qty, _ in self._t1_pending.get(ticker, []))
        else:
            t1_blocked = 0

        pos["available"] = max(0, total - frozen - t1_blocked)

    def _get_position_or_raise(self, ticker: str) -> dict:
        pos = self._positions.get(ticker)
        if pos is None:
            raise ValueError(f"No position for {ticker}")
        return pos
