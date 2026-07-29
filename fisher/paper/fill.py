from ..event.types import Bar, OrderSide
from ..oms.orders import Order


class FillSimulator:
    """撮合撮合模拟器。

    关键修正（对应量化系统改进清单 P0-3 / P2-16）：
    - 引入滑点（固定 bp + 可选成交量冲击），买抬高、卖压低；
    - 建模涨跌停：当日封板（收盘=最高/最低）时对应方向的单无法成交；
    - 复用原有限价校验逻辑。
    """

    def __init__(
        self,
        fill_price_mode: str = "current_close",
        price_limit_ratio: float | None = 0.10,
        min_volume_ratio: float = 0.1,
        slippage_bps: float = 0.0,
        model_price_limit: bool = True,
    ):
        self._mode = fill_price_mode
        self._price_limit_ratio = price_limit_ratio
        self._min_volume_ratio = min_volume_ratio
        self._slippage_bps = float(slippage_bps)
        self._model_price_limit = model_price_limit

    def check_fill(
        self, order: Order, bar: Bar, prev_close: float | None = None
    ) -> tuple[bool, float]:
        if order.ticker != bar.ticker:
            return False, 0.0

        # G1 MVP：市价单按"次根 bar 开盘价"撮合（信号 bar N → 成交 bar N+1 已是下一根，
        # 其 open 即真实市价单可成交价），且不接受限价约束。
        is_market = order.order_type == "market"
        if is_market:
            raw_price = bar.open
        else:
            raw_price = self._get_raw_price(bar)

        # P2-16：涨跌停封板时对应方向无法成交（市价单同样适用）
        if self._model_price_limit and self._is_limit_locked(order, bar, prev_close):
            return False, raw_price

        fill_price = self._apply_slippage(raw_price, order.side)

        if not is_market and not self._check_price_limit(order, fill_price):
            return False, fill_price

        if bar.volume == 0 or order.quantity > bar.volume * self._min_volume_ratio:
            return False, fill_price

        return True, fill_price

    def _get_raw_price(self, bar: Bar) -> float:
        if self._mode == "next_open":
            return bar.open
        elif self._mode == "current_close":
            return bar.close
        elif self._mode == "vwap":
            if bar.volume > 0:
                return bar.amount / bar.volume
            return bar.close
        elif self._mode == "ohlc4":
            return (bar.open + bar.high + bar.low + bar.close) / 4
        return bar.close

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """P0-3：买单边抬高、卖单边压低，模拟买卖价差与冲击成本。"""
        if self._slippage_bps <= 0 or price <= 0:
            return price
        slip = price * self._slippage_bps / 10000.0
        if side == OrderSide.BUY:
            return price + slip
        return price - slip

    def _is_limit_locked(
        self, order: Order, bar: Bar, prev_close: float | None = None
    ) -> bool:
        """基于前收盘价判断涨跌停封板。

        仅当（1）当根涨/跌幅触及涨跌停限价，且（2）收盘封死在最高/最低时，
        才判定为封板不可成交。缺少前收盘价（首根 bar）时无法判定，放行。
        避免把普通一字线/十字星误判为封板。
        """
        eps = 1e-9
        if bar.high <= 0 or bar.low <= 0:
            return False
        if prev_close is None or prev_close <= 0 or self._price_limit_ratio is None:
            return False

        up_limit = prev_close * (1 + self._price_limit_ratio)
        down_limit = prev_close * (1 - self._price_limit_ratio)

        # 涨停封死（收盘≈涨停价且封死在最高）：无法买入
        if (
            order.side == OrderSide.BUY
            and bar.close >= up_limit * (1 - 1e-4)
            and bar.close >= bar.high - eps
        ):
            return True
        # 跌停封死（收盘≈跌停价且封死在最低）：无法卖出
        if (
            order.side == OrderSide.SELL
            and bar.close <= down_limit * (1 + 1e-4)
            and bar.close <= bar.low + eps
        ):
            return True
        return False

    def _check_price_limit(self, order: Order, fill_price: float) -> bool:
        if self._price_limit_ratio is None:
            return True

        limit_upper = order.price * (1 + self._price_limit_ratio)
        limit_lower = order.price * (1 - self._price_limit_ratio)

        if order.side == OrderSide.BUY:
            return fill_price <= limit_upper
        else:
            return fill_price >= limit_lower
