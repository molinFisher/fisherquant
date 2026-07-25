from abc import ABC, abstractmethod
from ..event.types import OrderSide
from ..oms.orders import Order


class BrokerAdapter(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None:
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, dict]:
        ...

    @abstractmethod
    def get_account(self) -> dict:
        ...
