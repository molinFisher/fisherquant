import json

import pytest
from fastapi import WebSocketDisconnect
from jose import JWTError

import fisher.monitor.ws as ws_module
from fisher.monitor.ws import (
    ConnectionManager,
    _ws_auth_and_listen,
    ws_router,
)


class FakeWebSocket:
    """Minimal async stand-in for a FastAPI WebSocket."""

    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)

    async def receive_json(self):  # pragma: no cover - manager never receives
        raise WebSocketDisconnect()


class ScriptedWebSocket(FakeWebSocket):
    """WebSocket whose receive_json follows a scripted sequence."""

    def __init__(self, script):
        super().__init__()
        self._script = list(script)
        self._idx = 0

    async def receive_json(self):
        if self._idx >= len(self._script):
            raise WebSocketDisconnect()
        kind, payload = self._script[self._idx]
        self._idx += 1
        if kind == "raise":
            raise payload
        return payload


# --------------------------------------------------------------------------
# ConnectionManager
# --------------------------------------------------------------------------

async def test_connect_accepts_and_registers():
    cm = ConnectionManager()
    ws = FakeWebSocket()
    await cm.connect(ws, "overview")
    assert ws.accepted is True
    assert cm._connections["overview"] == [ws]


async def test_broadcast_delivers_to_channel():
    cm = ConnectionManager()
    ws = FakeWebSocket()
    await cm.connect(ws, "risk")
    msg = {"type": "risk_alert", "level": "warning"}
    await cm.broadcast("risk", msg)
    assert ws.sent == [msg]


async def test_broadcast_to_multiple_connections():
    cm = ConnectionManager()
    w1, w2 = FakeWebSocket(), FakeWebSocket()
    await cm.connect(w1, "orders")
    await cm.connect(w2, "orders")
    msg = {"type": "order_fill", "order_id": "o1"}
    await cm.broadcast("orders", msg)
    assert w1.sent == [msg]
    assert w2.sent == [msg]


async def test_broadcast_unknown_channel_is_noop():
    cm = ConnectionManager()
    # Must not raise even with zero listeners.
    await cm.broadcast("nope", {"type": "x"})


async def test_disconnect_stops_delivery():
    cm = ConnectionManager()
    ws = FakeWebSocket()
    await cm.connect(ws, "orders")
    await cm.broadcast("orders", {"type": "a"})
    await cm.disconnect(ws, "orders")
    await cm.broadcast("orders", {"type": "b"})
    # Only the first message should have been delivered.
    assert [m["type"] for m in ws.sent] == ["a"]
    assert ws not in cm._connections["orders"]


async def test_channels_are_isolated():
    cm = ConnectionManager()
    risk_ws = FakeWebSocket()
    order_ws = FakeWebSocket()
    await cm.connect(risk_ws, "risk")
    await cm.connect(order_ws, "orders")

    await cm.broadcast("risk", {"type": "risk_alert"})
    await cm.broadcast("orders", {"type": "order_fill"})

    assert [m["type"] for m in risk_ws.sent] == ["risk_alert"]
    assert [m["type"] for m in order_ws.sent] == ["order_fill"]


# --------------------------------------------------------------------------
# Message protocol (serialize / deserialize contract)
# --------------------------------------------------------------------------

def test_position_update_message_roundtrip():
    msg = {
        "type": "position_update",
        "channel": "overview",
        "symbol": "600519",
        "qty": 100,
        "avg_price": 100.5,
        "ts": "2024-01-02T09:30:00",
    }
    decoded = json.loads(json.dumps(msg))
    assert decoded == msg
    assert isinstance(decoded["qty"], int)
    assert isinstance(decoded["avg_price"], float)


def test_risk_alert_message_roundtrip():
    msg = {
        "type": "risk_alert",
        "channel": "risk",
        "level": "critical",
        "metric": "var",
        "value": 0.05,
    }
    decoded = json.loads(json.dumps(msg))
    assert decoded == msg
    assert isinstance(decoded["value"], float)
    assert decoded["level"] == "critical"


def test_order_fill_message_roundtrip():
    msg = {
        "type": "order_fill",
        "channel": "orders",
        "order_id": "ord-123",
        "symbol": "000001",
        "filled_qty": 50,
        "fill_price": 101.0,
    }
    decoded = json.loads(json.dumps(msg))
    assert decoded == msg
    assert isinstance(decoded["filled_qty"], int)
    assert decoded["order_id"] == "ord-123"


# --------------------------------------------------------------------------
# _ws_auth_and_listen
# --------------------------------------------------------------------------

async def test_auth_reject_missing_token():
    ws = ScriptedWebSocket([("msg", {})])  # no "token" key
    await _ws_auth_and_listen(ws, "overview")
    assert ws.closed is not None
    assert ws.closed[0] == 4001
    assert ws.accepted is False


async def test_auth_reject_non_dict_message():
    # First received frame is a JSON array, not an object -> .get fails -> 4001.
    ws = ScriptedWebSocket([("msg", ["not", "an", "object"])])
    await _ws_auth_and_listen(ws, "overview")
    assert ws.closed is not None
    assert ws.closed[0] == 4001


async def test_auth_reject_invalid_token(monkeypatch):
    def fake_auth(token):
        raise JWTError("invalid token")

    monkeypatch.setattr(ws_module, "get_current_user", fake_auth)
    ws = ScriptedWebSocket([("msg", {"token": "garbage"})])
    await _ws_auth_and_listen(ws, "overview")
    assert ws.closed is not None
    assert ws.closed[0] == 4001
    assert ws.accepted is False


async def test_auth_success_relays_and_disconnects(monkeypatch):
    def fake_auth(token):
        return "user"

    monkeypatch.setattr(ws_module, "get_current_user", fake_auth)
    ws = ScriptedWebSocket([
        ("msg", {"token": "good"}),
        ("msg", {"type": "position_update", "symbol": "A", "qty": 10}),
        ("raise", WebSocketDisconnect()),
    ])
    await _ws_auth_and_listen(ws, "overview")

    assert ws.accepted is True
    # The relayed client message must be broadcast back to the channel.
    assert ws.sent == [{"type": "position_update", "symbol": "A", "qty": 10}]


# --------------------------------------------------------------------------
# Router contract
# --------------------------------------------------------------------------

def test_router_defines_four_channels():
    paths = {route.path for route in ws_router.routes}
    assert paths == {"/ws/overview", "/ws/risk", "/ws/orders", "/ws/alerts"}
