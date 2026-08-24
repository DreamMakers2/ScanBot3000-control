from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Set

from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)


@dataclass(eq=False)
class WebSocketConnection:
    websocket: WebSocket
    queue: "asyncio.Queue[Dict[str, Any]]" = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    sender_task: asyncio.Task[None] | None = None


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: Set[WebSocketConnection] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> WebSocketConnection:
        await websocket.accept()
        connection = WebSocketConnection(websocket=websocket)
        connection.sender_task = asyncio.create_task(self._sender(connection))
        async with self._lock:
            self._connections.add(connection)
        LOGGER.info("WebSocket client connected, %d clients", len(self._connections))
        return connection

    async def disconnect(self, connection: WebSocketConnection) -> None:
        async with self._lock:
            self._connections.discard(connection)
        if connection.sender_task:
            connection.sender_task.cancel()
            try:
                await connection.sender_task
            except Exception:
                pass
        LOGGER.info("WebSocket client removed, %d clients", len(self._connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                connection.queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    connection.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    connection.queue.put_nowait(message)
                except asyncio.QueueFull:
                    LOGGER.warning("Dropping message for WebSocket client")

    async def _sender(self, connection: WebSocketConnection) -> None:
        websocket = connection.websocket
        try:
            while True:
                message = await connection.queue.get()
                await websocket.send_json(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("WebSocket send failed: %s", exc)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass


__all__ = ["WebSocketManager", "WebSocketConnection"]
