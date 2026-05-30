import asyncio
import json
import logging
from typing import Set, Any
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class MessageBus:
    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self._connections.discard(websocket)

    async def broadcast(self, event_type: str, data: Any):
        payload = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        dead = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    async def emit(self, event_type: str, data: Any):
        await self._queue.put((event_type, data))

    async def start(self):
        self._running = True
        while self._running:
            try:
                event_type, data = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self.broadcast(event_type, data)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Message bus error: %s", e)

    def stop(self):
        self._running = False


message_bus = MessageBus()
