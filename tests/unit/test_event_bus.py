import asyncio
import pytest
from fisher.event.bus import AsyncioEventBus, create_event_bus
from fisher.config.schemas import EventConfig
from fisher.event.types import Bar, Signal, OrderSide


class TestAsyncioEventBus:
    def test_subscribe_and_publish(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("bar", handler)
        bar = Bar(ticker="000001.SZ", close=10.0)

        with pytest.raises(RuntimeError, match="publish_sync"):
            bus.publish(bar)

        bus.publish_sync(bar)
        events = bus.drain_sync()
        assert len(events) == 1
        assert events[0].ticker == "000001.SZ"

    @pytest.mark.asyncio
    async def test_handler_receives_event(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(event: Bar):
            received.append(event)

        bus.subscribe("bar", handler)
        bar = Bar(ticker="000001.SZ", close=10.0)
        bus.publish(bar)

        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].ticker == "000001.SZ"
        assert received[0].close == 10.0

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        bus = AsyncioEventBus()
        r1, r2 = [], []

        async def h1(e): r1.append(e)
        async def h2(e): r2.append(e)

        bus.subscribe("signal", h1)
        bus.subscribe("signal", h2)
        sig = Signal(strategy="test", ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, confidence=1.0)
        bus.publish(sig)
        await asyncio.sleep(0.01)

        assert len(r1) == 1
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_wrong_event_type_not_delivered(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(e): received.append(e)

        bus.subscribe("bar", handler)
        sig = Signal(strategy="test", ticker="000001.SZ", market="a_share", side=OrderSide.BUY, quantity=100, confidence=1.0)
        bus.publish(sig)
        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(e): received.append(e)

        bus.subscribe("bar", handler)
        bus.unsubscribe("bar", handler)
        bus.publish(Bar(ticker="000001.SZ", close=10.0))
        await asyncio.sleep(0.01)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self):
        bus = AsyncioEventBus()
        r2 = []

        async def bad_handler(e): raise RuntimeError("crash")
        async def good_handler(e): r2.append(e)

        bus.subscribe("bar", bad_handler)
        bus.subscribe("bar", good_handler)
        bus.publish(Bar(ticker="000001.SZ", close=10.0))
        await asyncio.sleep(0.01)

        assert len(r2) == 1  # good handler still runs

    def test_publish_sync_stores_events(self):
        bus = AsyncioEventBus()
        bar1 = Bar(ticker="A", close=10.0)
        bar2 = Bar(ticker="B", close=20.0)
        bus.publish_sync(bar1)
        bus.publish_sync(bar2)
        events = bus.drain_sync()
        assert len(events) == 2
        assert events[0].ticker == "A"
        assert events[1].ticker == "B"
        assert len(bus.drain_sync()) == 0

    @pytest.mark.asyncio
    async def test_flush_awaits_pending_tasks(self):
        bus = AsyncioEventBus()
        received = []

        async def handler(e):
            await asyncio.sleep(0.01)
            received.append(e)

        bus.subscribe("bar", handler)
        bus.publish(Bar(ticker="000001.SZ", close=10.0))
        await bus.flush()
        assert len(received) == 1


class TestCreateEventBus:
    def test_creates_asyncio_by_default(self):
        bus = create_event_bus(EventConfig(backend="asyncio"))
        assert isinstance(bus, AsyncioEventBus)

    def test_redis_stub_raises(self):
        with pytest.raises(NotImplementedError):
            create_event_bus(EventConfig(backend="redis", redis_url="redis://localhost"))
