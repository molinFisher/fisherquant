import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .auth import get_current_user

ws_router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, channel: str):
        await ws.accept()
        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = []
            self._connections[channel].append(ws)

    async def disconnect(self, ws: WebSocket, channel: str):
        async with self._lock:
            if channel in self._connections and ws in self._connections[channel]:
                self._connections[channel].remove(ws)

    async def broadcast(self, channel: str, data: dict):
        async with self._lock:
            connections = list(self._connections.get(channel, []))
        for ws in connections:
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


async def _ws_auth_and_listen(ws: WebSocket, channel: str):
    try:
        auth_msg = await ws.receive_json()
        token = auth_msg.get("token", "")
        get_current_user(token)
    except Exception:
        await ws.close(code=4001)
        return
    await manager.connect(ws, channel)
    try:
        while True:
            data = await ws.receive_json()
            await manager.broadcast(channel, data)
    except WebSocketDisconnect:
        await manager.disconnect(ws, channel)


@ws_router.websocket("/ws/overview")
async def ws_overview(ws: WebSocket):
    await _ws_auth_and_listen(ws, "overview")


@ws_router.websocket("/ws/risk")
async def ws_risk(ws: WebSocket):
    await _ws_auth_and_listen(ws, "risk")


@ws_router.websocket("/ws/orders")
async def ws_orders(ws: WebSocket):
    await _ws_auth_and_listen(ws, "orders")


@ws_router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await _ws_auth_and_listen(ws, "alerts")
