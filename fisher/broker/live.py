"""真实券商接入占位实现（对应 P2-13）。

当前系统仅有 PaperEngine（仿真）。实盘需要接入具体券商的 REST/WebSocket
API（下单、撤单、持仓、资金、成交回报）。本类给出统一接口占位，提醒实现者
必须补齐以下能力，并保证账户状态线程安全（PaperEngine 已加锁作为参考）：

- submit_order / cancel_order：与券商柜台对接，返回真实委托号；
- on_bar / 成交推送：将券商成交回报回调进回测/实时引擎；
- get_account / get_positions：实时资金与持仓；
- 风控：实盘还需在提交前做更严格的资金/持仓校验与限速。
"""
from .adapter import BrokerAdapter
from ..event.types import OrderSide, OrderStatus
from ..oms.orders import Order


class LiveBrokerAdapter(BrokerAdapter):
    def __init__(self, credentials: dict | None = None):
        if credentials is None:
            raise ValueError(
                "LiveBrokerAdapter 需要券商凭证（api_key/account 等）；"
                "当前未配置，请使用 PaperEngine 进行仿真。"
            )
        self._credentials = credentials

    def submit_order(self, order: Order) -> Order:
        raise NotImplementedError("LiveBrokerAdapter.submit_order 未实现：请接入具体券商 API")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("LiveBrokerAdapter.cancel_order 未实现")

    def get_order(self, order_id: str) -> Order | None:
        raise NotImplementedError("LiveBrokerAdapter.get_order 未实现")

    def get_positions(self) -> dict[str, dict]:
        raise NotImplementedError("LiveBrokerAdapter.get_positions 未实现")

    def get_account(self) -> dict:
        raise NotImplementedError("LiveBrokerAdapter.get_account 未实现")
