"""G1 MVP 市价单撮合 + 撤单延迟/失败率 单测。"""
import random
from fisher.event.types import Bar, OrderSide, OrderStatus
from fisher.oms.orders import create_order
from fisher.paper.engine import PaperEngine
from fisher.paper.fill import FillSimulator


def _bar(ticker, o, h, l, c, v=100000, t=0.0):
    return Bar(ticker=ticker, open=o, high=h, low=l, close=c, volume=v, bar_time=t)


def test_market_order_fills_at_next_bar_open():
    sim = FillSimulator(fill_price_mode="current_close", slippage_bps=0.0)
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 0.0, order_type="market")
    bar = _bar("600519.SH", 10.5, 10.8, 10.2, 10.6)  # 次根 bar 开盘 10.5
    ok, price = sim.check_fill(order, bar)
    assert ok is True
    assert price == 10.5  # 市价单取开盘价，不受 mode=current_close 影响


def test_market_order_skips_limit_price_check():
    sim = FillSimulator(fill_price_mode="current_close", slippage_bps=0.0, price_limit_ratio=0.10)
    # 市价单无 price 约束；即便 limit-ratio 会被触发也不应因限价被拒
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 0.0, order_type="market")
    bar = _bar("600519.SH", 10.5, 10.8, 10.2, 10.6)
    ok, _ = sim.check_fill(order, bar)
    assert ok is True


def test_limit_order_still_uses_close_mode():
    sim = FillSimulator(fill_price_mode="current_close", slippage_bps=0.0)
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 10.0, order_type="limit")
    bar = _bar("600519.SH", 10.5, 10.8, 10.2, 10.6)
    ok, price = sim.check_fill(order, bar)
    assert ok is True and price == 10.6


def test_paper_market_order_fills_next_bar_open():
    pe = PaperEngine(initial_capital=1_000_000, slippage_bps=0.0)
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 0.0, order_type="market")
    pe.submit_order(order)
    # 信号 bar N
    pe.on_bar(_bar("600519.SH", 9.0, 9.2, 8.8, 9.1, t=1.0))
    # 成交 bar N+1：开盘价 10.5
    filled = pe.on_bar(_bar("600519.SH", 10.5, 10.8, 10.2, 10.6, t=2.0))
    assert len(filled) == 1
    assert filled[0].filled_price == 10.5
    assert filled[0].order_type == "market"


def test_cancel_failure_rate():
    # 固定种子确保可复现：失败率 1.0 → 第一次撤单必失败
    pe = PaperEngine(initial_capital=1_000_000, cancel_failure_rate=1.0, rng_seed=42)
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 10.0)
    pe.submit_order(order)
    assert pe.cancel_order(order.order_id) is False
    assert pe._cancel_failures == 1
    # 订单仍存活
    assert pe.get_order(order.order_id).is_active is True


def test_cancel_delay_bars():
    pe = PaperEngine(initial_capital=1_000_000, cancel_delay_bars=2, slippage_bps=0.0)
    # 限价 9.0 << 市价 10.1 → 不会成交，便于验证撤单延迟生效
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 9.0)
    pe.submit_order(order)
    # 请求撤单（被接受，但 2 根 bar 后才生效）
    assert pe.cancel_order(order.order_id) is True
    assert pe.get_order(order.order_id).is_active is True
    # bar N+1：撤单未生效，订单仍可挂留
    pe.on_bar(_bar("600519.SH", 10.0, 10.2, 9.8, 10.1, t=1.0))
    assert pe.get_order(order.order_id).is_active is True
    # bar N+2：撤单生效（订单被取消而非成交）
    pe.on_bar(_bar("600519.SH", 10.0, 10.2, 9.8, 10.1, t=2.0))
    assert pe.get_order(order.order_id).is_terminal is True
    assert pe.get_order(order.order_id).status == OrderStatus.CANCELLED


def test_default_paper_backward_compatible_no_cancel_effect():
    pe = PaperEngine(initial_capital=1_000_000)
    order = create_order("600519.SH", "a_share", "stock", OrderSide.BUY, 100, 10.0)
    pe.submit_order(order)
    # 默认无延迟/无失败 → 立即撤单成功
    assert pe.cancel_order(order.order_id) is True
    assert pe.get_order(order.order_id).is_terminal is True
