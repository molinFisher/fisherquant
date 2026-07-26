"""LiveBrokerAdapter 与 BrokerAdapter 接口契约测试（P2-13）。

覆盖：
- LiveBrokerAdapter 缺凭证构造抛 ValueError（而非 NotImplementedError）；
- 提供凭证时正常构造，且未实现的交易接口抛 NotImplementedError；
- BrokerAdapter 作为 ABC 不可直接实例化；
- 一个最小的具名子类实现全部抽象方法后，可实例化且按默认契约工作。
"""
import pytest
from fisher.broker.adapter import BrokerAdapter
from fisher.broker.live import LiveBrokerAdapter
from fisher.event.types import OrderSide, OrderStatus
from fisher.oms.orders import create_order


def _make_order(ticker="000001.SZ", side=OrderSide.BUY, quantity=100, price=10.0):
    return create_order(ticker, "a_share", "stock", side, quantity, price)


class TestLiveBrokerMissingCredentials:
    def test_none_raises_value_error(self):
        # 源码约定：credentials 为 None 必须抛 ValueError
        with pytest.raises(ValueError, match="凭证"):
            LiveBrokerAdapter(credentials=None)

    def test_default_none_raises_value_error(self):
        # 默认参数即 None，同样应抛 ValueError
        with pytest.raises(ValueError, match="凭证"):
            LiveBrokerAdapter()

    def test_empty_dict_is_accepted(self):
        # 一旦给出 dict（即使是空 dict），构造不应抛错——凭证"存在"
        adapter = LiveBrokerAdapter(credentials={})
        assert adapter._credentials == {}


class TestLiveBrokerInterfaceContract:
    def test_is_broker_adapter_subclass(self):
        assert issubclass(LiveBrokerAdapter, BrokerAdapter)

    def test_implements_all_abstract_methods(self):
        # 给出凭证后，5 个交易接口应已"实现"（即使只是抛 NotImplementedError）
        adapter = LiveBrokerAdapter(credentials={"api_key": "x", "account": "y"})
        assert isinstance(adapter, BrokerAdapter)
        for method in ("submit_order", "cancel_order", "get_order",
                       "get_positions", "get_account"):
            assert callable(getattr(adapter, method))

    def test_submit_order_not_implemented(self):
        adapter = LiveBrokerAdapter(credentials={"api_key": "x"})
        with pytest.raises(NotImplementedError):
            adapter.submit_order(_make_order())

    def test_cancel_order_not_implemented(self):
        adapter = LiveBrokerAdapter(credentials={"api_key": "x"})
        with pytest.raises(NotImplementedError):
            adapter.cancel_order("ORD-000001")

    def test_get_order_not_implemented(self):
        adapter = LiveBrokerAdapter(credentials={"api_key": "x"})
        with pytest.raises(NotImplementedError):
            adapter.get_order("ORD-000001")

    def test_get_positions_not_implemented(self):
        adapter = LiveBrokerAdapter(credentials={"api_key": "x"})
        with pytest.raises(NotImplementedError):
            adapter.get_positions()

    def test_get_account_not_implemented(self):
        adapter = LiveBrokerAdapter(credentials={"api_key": "x"})
        with pytest.raises(NotImplementedError):
            adapter.get_account()


class _MinimalBroker(BrokerAdapter):
    """最小具名实现，用于验证 BrokerAdapter 的抽象契约。"""

    def __init__(self):
        self.orders = {}

    def submit_order(self, order):
        self.orders[order.order_id] = order
        return order

    def cancel_order(self, order_id):
        return order_id in self.orders

    def get_order(self, order_id):
        return self.orders.get(order_id)

    def get_positions(self):
        return {}

    def get_account(self):
        return {"cash": 0.0}


class TestBrokerAdapterContract:
    def test_cannot_instantiate_abstract(self):
        # ABC 含未实现的抽象方法，直接实例化应失败
        with pytest.raises(TypeError):
            BrokerAdapter()

    def test_concrete_subclass_instantiable(self):
        broker = _MinimalBroker()
        assert isinstance(broker, BrokerAdapter)

    def test_concrete_subclass_default_behaviors(self):
        broker = _MinimalBroker()
        order = _make_order()
        returned = broker.submit_order(order)
        assert returned.order_id == order.order_id
        assert broker.get_order(order.order_id) is returned
        # cancel 一个存在的订单返回 True
        assert broker.cancel_order(order.order_id) is True
        # 不存在的订单 cancel 返回 False
        assert broker.cancel_order("nope") is False
        # 默认持仓为空 dict
        assert broker.get_positions() == {}
        # 默认账户返回 cash=0
        acct = broker.get_account()
        assert acct["cash"] == 0.0
