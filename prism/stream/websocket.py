"""WebSocket frame reassembler."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from prism.models import WSFrame, WSMessage


# WebSocket opcodes
WS_OP_CONTINUATION = 0x0
WS_OP_TEXT = 0x1
WS_OP_BINARY = 0x2
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA


class WebSocketReassembler:
    """
    Reassembles fragmented WebSocket frames into complete messages.

    Usage:
        reassembler = WebSocketReassembler()
        reassembler.feed_frame(conn_id, frame)
        messages = reassembler.get_conversation(conn_id)
    """

    def __init__(self):
        self._fragments: dict[str, list[WSFrame]] = defaultdict(list)
        self._messages: list[WSMessage] = []

    def feed_frame(self, conn_id: str, frame: WSFrame):
        """Feed a single WebSocket frame."""
        # Control frames are never fragmented — handle immediately
        if frame.opcode in (WS_OP_CLOSE, WS_OP_PING, WS_OP_PONG):
            msg = WSMessage(
                conn_id=conn_id,
                opcode=frame.opcode,
                payload=frame.payload,
                timestamp_start=frame.timestamp,
                timestamp_end=frame.timestamp,
                direction=frame.direction,
            )
            self._messages.append(msg)
            return

        self._fragments[conn_id].append(frame)

        if frame.fin:
            fragments = self._fragments[conn_id]
            opcode = fragments[0].opcode if fragments[0].opcode != WS_OP_CONTINUATION else WS_OP_TEXT
            payload = b"".join(f.payload for f in fragments)
            msg = WSMessage(
                conn_id=conn_id,
                opcode=opcode,
                payload=payload,
                timestamp_start=fragments[0].timestamp,
                timestamp_end=frame.timestamp,
                direction=frame.direction,
            )
            self._messages.append(msg)
            self._fragments[conn_id] = []

    def get_conversation(self, conn_id: str) -> list[WSMessage]:
        """Return all messages for a connection in order."""
        return [m for m in self._messages if m.conn_id == conn_id]

    def get_all_messages(self) -> list[WSMessage]:
        return list(self._messages)

    def to_dict_list(self, conn_id: str) -> list[dict]:
        """Serialize messages to dicts for storage."""
        result = []
        for msg in self.get_conversation(conn_id):
            try:
                text = msg.payload.decode("utf-8", errors="replace")
            except Exception:
                text = repr(msg.payload)
            result.append(
                {
                    "opcode": msg.opcode,
                    "direction": msg.direction,
                    "payload": text,
                    "timestamp_start": msg.timestamp_start.isoformat(),
                    "timestamp_end": msg.timestamp_end.isoformat(),
                }
            )
        return result

    def format_report_section(self, conn_id: str, upgrade_request: str = "") -> str:
        """Render a report section for a WebSocket conversation."""
        lines = [
            "========== [WebSocket Session] ==========",
            f"Connection ID: {conn_id}",
        ]
        if upgrade_request:
            lines.append("Upgrade Request:")
            for l in upgrade_request.splitlines():
                lines.append(f"  {l}")
            lines.append("")

        for i, msg in enumerate(self.get_conversation(conn_id), 1):
            direction = "Client → Server" if msg.direction == "client" else "Server → Client"
            ts = msg.timestamp_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            lines.append(f"--- Frame #{i} ({direction}) [{ts}] ---")
            try:
                lines.append(msg.payload.decode("utf-8", errors="replace"))
            except Exception:
                lines.append(f"[BINARY: {len(msg.payload)} bytes]")
            lines.append("")

        return "\n".join(lines)
