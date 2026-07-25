from ..event.types import Signal, OrderPending, OrderSide, OrderStatus
from .methods import equal_weight, risk_parity, kelly


class PortfolioBuilder:
    def __init__(
        self,
        method: str = "equal_weight",
        max_positions: int = 20,
        conflict_mode: str = "weighted_merge",
    ):
        self.method = method
        self.max_positions = max_positions
        self.conflict_mode = conflict_mode
        self._current_holdings: dict[str, float] = {}

    def build_orders(
        self,
        signals: list[Signal],
        capital: float,
    ) -> list[OrderPending]:
        merged = self._merge_signals(signals)
        weights = self._compute_weights(merged, capital)
        orders = self._weights_to_orders(weights, capital)
        return orders

    def _merge_signals(self, signals: list[Signal]) -> dict[str, dict]:
        ticker_signals: dict[str, list[Signal]] = {}
        for s in signals:
            ticker_signals.setdefault(s.ticker, []).append(s)

        merged: dict[str, dict] = {}
        for ticker, sigs in ticker_signals.items():
            if len(sigs) > 1 and self.conflict_mode == "skip_conflict":
                continue
            if self.conflict_mode == "weighted_merge":
                total_qty = sum(s.quantity for s in sigs)
                avg_confidence = sum(s.confidence for s in sigs) / len(sigs)
                dominant = max(sigs, key=lambda s: s.confidence)
                merged[ticker] = {
                    "ticker": ticker,
                    "market": dominant.market,
                    "side": dominant.side,
                    "quantity": total_qty,
                    "confidence": avg_confidence,
                }
            elif self.conflict_mode == "first_wins":
                s = sigs[0]
                merged[ticker] = {
                    "ticker": ticker,
                    "market": s.market,
                    "side": s.side,
                    "quantity": s.quantity,
                    "confidence": s.confidence,
                }
            else:
                s = sigs[0]
                merged[ticker] = {
                    "ticker": ticker,
                    "market": s.market,
                    "side": s.side,
                    "quantity": s.quantity,
                    "confidence": s.confidence,
                }
        return merged

    def _compute_weights(self, merged: dict, capital: float) -> dict:
        if self.method == "equal_weight":
            return equal_weight(merged, self.max_positions)
        elif self.method == "risk_parity":
            return risk_parity(merged, capital)
        elif self.method == "kelly":
            return kelly(merged)
        return equal_weight(merged, self.max_positions)

    def _weights_to_orders(self, weights: dict, capital: float) -> list[OrderPending]:
        orders: list[OrderPending] = []
        for ticker, weight in weights.items():
            allocation = capital * weight
            if allocation <= 0:
                continue
            orders.append(
                OrderPending(
                    ticker=ticker,
                    market="a_share",
                    side=OrderSide.BUY,
                    quantity=1,
                    price=allocation,
                    order_type="limit",
                    status=OrderStatus.PENDING,
                )
            )
        return orders
