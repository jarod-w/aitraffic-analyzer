"""mitmproxy addon — PRISM core data collection layer."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from mitmproxy import http
from mitmproxy.websocket import WebSocketMessage

from prism.config import settings
from prism.identification.engine import SignatureDB, get_signature_db
from prism.identification.metadata import MetadataExtractor
from prism.models import AITrafficRecord, AIMetadata, WSFrame
from prism.stream.sse import SSEReassembler
from prism.stream.websocket import WebSocketReassembler


class PrismAddon:
    """
    mitmproxy addon that intercepts HTTP(S) traffic, identifies AI-related
    flows, and emits AITrafficRecord objects for storage.
    """

    def __init__(
        self,
        task_id: str,
        on_record: Optional[Callable[[AITrafficRecord], Any]] = None,
        sig_db: Optional[SignatureDB] = None,
    ):
        self.task_id = task_id
        self.on_record = on_record  # async or sync callback
        self.sig_db = sig_db or get_signature_db()
        self.metadata_extractor = MetadataExtractor()
        self.sse_reassembler = SSEReassembler()
        self.ws_reassembler = WebSocketReassembler()
        self._sequence = 0
        self._ws_upgrade_requests: dict[str, str] = {}  # flow_id -> raw upgrade req

    # ------------------------------------------------------------------
    # mitmproxy hooks
    # ------------------------------------------------------------------

    def request(self, flow: http.HTTPFlow):
        flow.metadata["prism_task_id"] = self.task_id
        flow.metadata["capture_time"] = datetime.utcnow().isoformat()

    def response(self, flow: http.HTTPFlow):
        """Main data collection point for HTTP request/response pairs."""
        if flow.websocket is not None:
            # Upgrade request — store raw for later
            self._ws_upgrade_requests[flow.id] = self._dump_raw_request(flow)
            return

        host = flow.request.pretty_host
        path = flow.request.path
        req_headers = dict(flow.request.headers)

        body = None
        if settings.capture_body:
            body = flow.request.get_content(limit=settings.max_body_size)

        match = self.sig_db.identify(
            host=host,
            path=path,
            headers=req_headers,
            body=body,
        )
        if not match.is_ai:
            return

        self._sequence += 1
        seq = self._sequence

        # Raw packets
        raw_req = self._dump_raw_request(flow)
        raw_resp = self._dump_raw_response(flow)

        # Response body
        resp_body_bytes = None
        if flow.response:
            resp_body_bytes = flow.response.get_content(limit=settings.max_body_size)

        # SSE handling
        stream_type = None
        stream_events = None
        aggregated = None
        if flow.response:
            ct = flow.response.headers.get("content-type", "")
            if "text/event-stream" in ct and resp_body_bytes:
                stream_type = "sse"
                events = self.sse_reassembler.parse_stream(resp_body_bytes)
                stream_events = self.sse_reassembler.to_dict_list(events)
                aggregated = self.sse_reassembler.aggregate_completion(events)

        # Metadata
        meta = self.metadata_extractor.extract(
            provider=self.sig_db.provider_display_name(match.provider),
            method=flow.request.method,
            url=flow.request.pretty_url,
            request_headers=req_headers,
            request_body=body,
            response_headers=dict(flow.response.headers) if flow.response else None,
            response_body=resp_body_bytes,
            timestamp=datetime.utcnow(),
        )

        record = AITrafficRecord(
            id=f"rec-{uuid4().hex[:12]}",
            task_id=self.task_id,
            sequence=seq,
            provider=self.sig_db.provider_display_name(match.provider),
            service_type=match.service_type,
            confidence=match.confidence,
            method=flow.request.method,
            url=flow.request.pretty_url,
            request_headers=req_headers,
            request_body=self._body_str(body, req_headers),
            response_status=flow.response.status_code if flow.response else None,
            response_headers=dict(flow.response.headers) if flow.response else None,
            response_body=self._body_str(resp_body_bytes, dict(flow.response.headers) if flow.response else {}),
            raw_request=raw_req,
            raw_response=raw_resp,
            metadata=meta,
            stream_type=stream_type,
            stream_events=stream_events,
            aggregated_response=aggregated,
            timestamp=datetime.utcnow(),
        )

        if self.on_record:
            try:
                result = self.on_record(record)
                if asyncio.iscoroutine(result):
                    asyncio.get_event_loop().create_task(result)
            except Exception:
                pass

    def websocket_message(self, flow: http.HTTPFlow):
        """WebSocket message interception."""
        msg = flow.websocket.messages[-1]
        frame = WSFrame(
            payload=msg.content if isinstance(msg.content, bytes) else msg.content.encode(),
            opcode=1 if msg.type == "text" else 2,
            direction="client" if msg.from_client else "server",
            timestamp=datetime.utcnow(),
            fin=True,  # mitmproxy presents already-assembled frames
        )
        self.ws_reassembler.feed_frame(flow.id, frame)

    def websocket_end(self, flow: http.HTTPFlow):
        """Emit a WebSocket traffic record when the connection closes."""
        host = flow.request.pretty_host
        if not self.sig_db.is_ai_host(host):
            return

        self._sequence += 1
        seq = self._sequence
        conn_id = flow.id
        upgrade_raw = self._ws_upgrade_requests.get(conn_id, "")

        messages = self.ws_reassembler.get_conversation(conn_id)
        stream_events = self.ws_reassembler.to_dict_list(conn_id)

        raw_req = upgrade_raw
        raw_resp = self.ws_reassembler.format_report_section(conn_id, upgrade_raw)

        meta = self.metadata_extractor.extract(
            provider=host,
            method="GET",
            url=flow.request.pretty_url,
            request_headers=dict(flow.request.headers),
            request_body=None,
            response_headers=dict(flow.response.headers) if flow.response else None,
            response_body=None,
            timestamp=datetime.utcnow(),
        )

        record = AITrafficRecord(
            id=f"rec-{uuid4().hex[:12]}",
            task_id=self.task_id,
            sequence=seq,
            provider=host,
            service_type="realtime",
            confidence=0.90,
            method="WS",
            url=flow.request.pretty_url,
            request_headers=dict(flow.request.headers),
            raw_request=raw_req,
            raw_response=raw_resp,
            metadata=meta,
            stream_type="websocket",
            stream_events=stream_events,
            timestamp=datetime.utcnow(),
        )

        if self.on_record:
            try:
                result = self.on_record(record)
                if asyncio.iscoroutine(result):
                    asyncio.get_event_loop().create_task(result)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _dump_raw_request(self, flow: http.HTTPFlow) -> str:
        req = flow.request
        lines = [f"{req.method} {req.pretty_url} {req.http_version}"]
        for k, v in req.headers.items():
            lines.append(f"{self._redact_header(k, v)}")
        lines.append("")
        body = req.get_content(limit=settings.max_body_size)
        if body:
            lines.append(self._body_str(body, dict(req.headers)))
        return "\n".join(lines)

    def _dump_raw_response(self, flow: http.HTTPFlow) -> str:
        if not flow.response:
            return ""
        resp = flow.response
        lines = [f"{flow.request.http_version} {resp.status_code} {resp.reason}"]
        for k, v in resp.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        body = resp.get_content(limit=settings.max_body_size)
        if body:
            lines.append(self._body_str(body, dict(resp.headers)))
        return "\n".join(lines)

    def _redact_header(self, key: str, value: str) -> str:
        if not settings.redact_secrets:
            return f"{key}: {value}"
        k = key.lower()
        if k == "authorization":
            return f"{key}: [REDACTED]"
        if k == "cookie":
            return f"{key}: [REDACTED]"
        if k == "x-api-key":
            return f"{key}: {value[:8]}..." if len(value) > 8 else f"{key}: [REDACTED]"
        return f"{key}: {value}"

    def _body_str(self, body: Optional[bytes], headers: dict) -> str:
        if not body:
            return ""
        ct = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
        if "application/octet-stream" in ct or "multipart/form-data" in ct:
            sha = hashlib.sha256(body).hexdigest()
            return f"[BINARY DATA: {len(body)} bytes, SHA256: {sha}]"
        try:
            return body.decode("utf-8", errors="replace")
        except Exception:
            sha = hashlib.sha256(body).hexdigest()
            return f"[BINARY DATA: {len(body)} bytes, SHA256: {sha}]"
