import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .auth import get_current_user

ws_router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, channel: str):
        await ws.accept()
        if channel not in self._connections:
            self._connections[channel] = []
        self._connections[channel].append(ws)

    def disconnect(self, ws: WebSocket, channel: str):
        if channel in self._connections and ws in self._connections[channel]:
            self._connections[channel].remove(ws)

    async def broadcast(self, channel: str, data: dict):
        for ws in self._connections.get(channel, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


@ws_router.websocket("/ws/overview")
async def ws_overview(ws: WebSocket, token: str = ""):
    try:
        get_current_user(token)
    except Exception:
        await ws.close(code=4001)
        return
    await manager.connect(ws, "overview")
    try:
        while True:
            data = await ws.receive_json()
            await manager.broadcast("overview", data)
    except WebSocketDisconnect:
        manager.disconnect(ws, "overview")


@ws_router.websocket("/ws/risk")
async def ws_risk(ws: WebSocket, token: str = ""):
    try:
        get_current_user(token)
    except Exception:
        await ws.close(code=4001)
        return
    await manager.connect(ws, "risk")
    try:
        while True:
            data = await ws.receive_json()
            await manager.broadcast("risk", data)
    except WebSocketDisconnect:
        manager.disconnect(ws, "risk")


@ws_router.websocket("/ws/orders")
async def ws_orders(ws: WebSocket, token: str = ""):
    try:
        get_current_user(token)
    except Exception:
        await ws.close(code=4001)
        return
    await manager.connect(ws, "orders")
    try:
        while True:
            data = await ws.receive_json()
            await manager.broadcast("orders", data)
    except WebSocketDisconnect:
        manager.disconnect(ws, "orders")


@ws_router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket, token: str = ""):
    try:
        get_current_user(token)
    except Exception:
        await ws.close(code=4001)
        return
    await manager.connect(ws, "alerts")
    try:
        while True:
            data = await ws.receive_json()
            await manager.broadcast("alerts", data)
    except WebSocketDisconnect:
        manager.disconnect(ws, "alerts")
