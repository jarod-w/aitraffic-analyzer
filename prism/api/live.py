"""WebSocket live-feed manager — pushes new records to connected frontends."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class LiveFeedManager:
    """
    Maintains a registry of WebSocket connections keyed by task_id.
    When a new record is captured, broadcast it to all subscribers.
    """

    def __init__(self):
        # task_id -> set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, task_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[task_id].add(ws)
        logger.debug("WS connected: task=%s total=%d", task_id, len(self._connections[task_id]))

    def disconnect(self, task_id: str, ws: WebSocket):
        self._connections[task_id].discard(ws)
        if not self._connections[task_id]:
            del self._connections[task_id]

    async def broadcast(self, task_id: str, message: dict[str, Any]):
        dead = set()
        for ws in list(self._connections.get(task_id, set())):
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(task_id, ws)

    async def broadcast_record(self, task_id: str, record_summary: dict):
        await self.broadcast(
            task_id,
            {
                "type": "new_record",
                "task_id": task_id,
                "record": record_summary,
            },
        )

    async def broadcast_task_update(self, task_id: str, status: str, record_count: int):
        await self.broadcast(
            task_id,
            {
                "type": "task_update",
                "task_id": task_id,
                "data": {"status": status, "record_count": record_count},
            },
        )


# Singleton
live_manager = LiveFeedManager()
