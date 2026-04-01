"""WebSocket live-feed endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from prism.api.live import live_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live"])


@router.websocket("/api/v1/tasks/{task_id}/live")
async def live_feed(task_id: str, websocket: WebSocket):
    """
    Subscribe to real-time AI traffic records for a task.

    Pushes JSON messages of shape:
      {"type": "new_record", "task_id": "...", "record": {...}}
      {"type": "task_update", "task_id": "...", "data": {"status": "...", "record_count": N}}
    """
    await live_manager.connect(task_id, websocket)
    try:
        while True:
            # Keep connection alive — we don't process incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        live_manager.disconnect(task_id, websocket)
    except Exception as e:
        logger.debug("WS error for task %s: %s", task_id, e)
        live_manager.disconnect(task_id, websocket)
