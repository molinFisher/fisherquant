from ..event.types import OrderStatus
from .orders import Order, ORDER_STATUS_TRANSITIONS


class OMSEngine:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._condition_queue: list[Order] = []

    VALID_CONDITION_TYPES = {"stop_loss", "take_profit"}

    def submit(self, order: Order) -> None:
        if order.condition_type is not None:
            if order.condition_type not in self.VALID_CONDITION_TYPES:
                raise ValueError(
                    f"Invalid condition_type '{order.condition_type}'. "
                    f"Must be one of {self.VALID_CONDITION_TYPES}"
                )
            if order.condition_price is None:
                raise ValueError("condition_price must be set when condition_type is provided")
        if order.condition_price is not None and order.condition_type is not None:
            self._condition_queue.append(order)
            self._orders[order.order_id] = order
            return

        self._transition(order, OrderStatus.PENDING)
        self._orders[order.order_id] = order

    def cancel(self, order_id: str) -> None:
        order = self._get_order_or_raise(order_id)
        self._transition(order, OrderStatus.CANCELLED)

    def update_status(self, order_id: str, new_status: OrderStatus) -> None:
        order = self._get_order_or_raise(order_id)
        self._transition(order, new_status)

    def update_fill(
        self,
        order_id: str,
        filled_qty: int,
        filled_price: float,
        commission: float = 0.0,
    ) -> None:
        order = self._get_order_or_raise(order_id)
        total_filled = order.filled_qty + filled_qty
        if total_filled > order.quantity:
            raise ValueError(
                f"filled quantity ({total_filled}) exceeds order quantity ({order.quantity})"
            )

        if filled_qty > 0:
            prev_cost = order.filled_qty * order.filled_price
            new_cost = filled_qty * filled_price
            order.filled_price = (prev_cost + new_cost) / total_filled if total_filled > 0 else 0.0

        order.filled_qty = total_filled
        order.commission += commission

        target = OrderStatus.FILLED if total_filled >= order.quantity else OrderStatus.PARTIALLY_FILLED
        if order.status not in {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}:
            self._transition(order, OrderStatus.PARTIALLY_FILLED)
        if target == OrderStatus.FILLED and order.status != OrderStatus.FILLED:
            self._transition(order, OrderStatus.FILLED)

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_pending(self) -> list[Order]:
        return [o for o in self._orders.values() if not o.is_terminal]

    def get_all_orders(self) -> list[Order]:
        return list(self._orders.values())

    def check_conditions(self, ticker: str, current_price: float) -> list[Order]:
        triggered: list[Order] = []
        remaining: list[Order] = []

        for order in self._condition_queue:
            if order.ticker != ticker:
                remaining.append(order)
                continue

            should_trigger = False
            if order.condition_type == "stop_loss" and current_price <= (order.condition_price or 0):
                should_trigger = True
            elif order.condition_type == "take_profit" and current_price >= (order.condition_price or 0):
                should_trigger = True

            if should_trigger:
                self._transition(order, OrderStatus.PENDING)
                triggered.append(order)
            else:
                remaining.append(order)

        self._condition_queue = remaining
        return triggered

    def _transition(self, order: Order, new_status: OrderStatus) -> None:
        allowed = ORDER_STATUS_TRANSITIONS.get(order.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition order {order.order_id} "
                f"from {order.status.value} to {new_status.value}"
            )
        order.status = new_status

    def _get_order_or_raise(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")
        return order
