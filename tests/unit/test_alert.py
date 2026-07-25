import pytest
import time
import sys
import io
from fisher.alert.service import AlertService, ConsoleChannel


class TestAlertService:
    def test_subscribe_and_notify(self):
        svc = AlertService()
        received = []

        def callback(event):
            received.append(event)

        svc.subscribe("risk", callback)
        svc.notify("risk", {"message": "test alert"})
        assert len(received) == 1
        assert received[0]["message"] == "test alert"

    def test_unsubscribe(self):
        svc = AlertService()
        received = []

        def callback(event):
            received.append(event)

        svc.subscribe("risk", callback)
        svc.unsubscribe("risk", callback)
        svc.notify("risk", {"message": "test"})
        assert len(received) == 0

    def test_wrong_event_type_not_received(self):
        svc = AlertService()
        received = []

        def callback(event):
            received.append(event)

        svc.subscribe("risk", callback)
        svc.notify("order", {"message": "test"})
        assert len(received) == 0

    def test_multiple_subscribers(self):
        svc = AlertService()
        r1, r2 = [], []

        def cb1(e): r1.append(e)
        def cb2(e): r2.append(e)

        svc.subscribe("risk", cb1)
        svc.subscribe("risk", cb2)
        svc.notify("risk", {"msg": "a"})
        assert len(r1) == 1
        assert len(r2) == 1

    def test_different_event_types(self):
        svc = AlertService()
        risk_received = []
        order_received = []

        def risk_cb(e): risk_received.append(e)
        def order_cb(e): order_received.append(e)

        svc.subscribe("risk", risk_cb)
        svc.subscribe("order", order_cb)
        svc.notify("risk", {"msg": "r"})
        svc.notify("order", {"msg": "o"})

        assert len(risk_received) == 1
        assert len(order_received) == 1


class TestConsoleChannel:
    def test_print_to_stderr(self):
        ch = ConsoleChannel()
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            ch.send("risk", {"message": "alert!"})
        finally:
            sys.stderr = old_stderr
        output = captured.getvalue()
        assert "alert!" in output
        assert "[risk]" in output


class TestThrottling:
    def test_throttle_allows_first(self):
        svc = AlertService(throttle_seconds=60)
        received = []

        def cb(e): received.append(e)

        svc.subscribe("risk", cb)
        svc.notify("risk", {"msg": "first"})
        assert len(received) == 1

    def test_throttle_blocks_rapid(self):
        svc = AlertService(throttle_seconds=60)
        received = []

        def cb(e): received.append(e)

        svc.subscribe("risk", cb)
        svc.notify("risk", {"msg": "first"})
        svc.notify("risk", {"msg": "second"})
        assert len(received) == 1  # second is throttled

    def test_throttle_reset(self):
        svc = AlertService(throttle_seconds=0)
        received = []

        def cb(e): received.append(e)

        svc.subscribe("risk", cb)
        svc.notify("risk", {"msg": "first"})
        svc.notify("risk", {"msg": "second"})
        assert len(received) == 2  # no throttle with 0 seconds

    def test_throttle_per_event_type(self):
        svc = AlertService(throttle_seconds=60)
        risk_received = []
        order_received = []

        def risk_cb(e): risk_received.append(e)
        def order_cb(e): order_received.append(e)

        svc.subscribe("risk", risk_cb)
        svc.subscribe("order", order_cb)
        svc.notify("risk", {"msg": "r1"})
        svc.notify("order", {"msg": "o1"})
        svc.notify("risk", {"msg": "r2"})  # throttled
        svc.notify("order", {"msg": "o2"})  # throttled

        assert len(risk_received) == 1
        assert len(order_received) == 1
