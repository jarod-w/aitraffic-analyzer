"""Server-Sent Events (SSE) stream reassembler."""

from __future__ import annotations

import json
from typing import Optional

from prism.models import SSEEvent


class SSEReassembler:
    """
    Parses raw SSE (text/event-stream) bodies into discrete SSEEvent objects
    and aggregates the token stream into a complete response string.
    """

    def parse_stream(self, raw_body: bytes) -> list[SSEEvent]:
        """Parse an SSE stream body into a list of SSEEvent objects."""
        events: list[SSEEvent] = []
        current = SSEEvent()

        text = raw_body.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line == "":
                # Empty line = event boundary
                if current.data:
                    events.append(current)
                current = SSEEvent()
            elif line.startswith("data:"):
                current.data += line[5:].lstrip(" ")
            elif line.startswith("event:"):
                current.event_type = line[6:].strip()
            elif line.startswith("id:"):
                current.event_id = line[3:].strip()
            elif line.startswith("retry:"):
                try:
                    current.retry = int(line[6:].strip())
                except ValueError:
                    pass
            # Lines starting with ':' are comments — skip

        # Flush last event if body didn't end with blank line
        if current.data:
            events.append(current)

        return events

    def aggregate_completion(self, events: list[SSEEvent]) -> str:
        """
        Aggregate streaming token deltas into a full response string.
        Handles OpenAI, DeepSeek, Anthropic, and generic formats.
        """
        full_text = ""
        for event in events:
            if event.data in ("[DONE]", ""):
                continue
            try:
                payload = json.loads(event.data)
            except json.JSONDecodeError:
                continue

            delta = self._extract_delta(payload)
            if delta:
                full_text += delta

        return full_text

    def _extract_delta(self, payload: dict) -> str:
        # OpenAI / DeepSeek format: choices[0].delta.content
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    return content
                # Tool call / reasoning
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str):
                    return reasoning

        # Anthropic format: delta.text
        delta = payload.get("delta", {})
        if isinstance(delta, dict):
            text = delta.get("text")
            if isinstance(text, str):
                return text

        # Google Gemini format: candidates[0].content.parts[0].text
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts and isinstance(parts[0].get("text"), str):
                return parts[0]["text"]

        return ""

    def to_dict_list(self, events: list[SSEEvent]) -> list[dict]:
        return [
            {
                "event_type": e.event_type,
                "data": e.data,
                "id": e.event_id,
            }
            for e in events
        ]

    def format_report_section(
        self,
        events: list[SSEEvent],
        aggregated: str,
        duration_s: Optional[float] = None,
    ) -> str:
        """Render SSE section for the report."""
        dur_str = f", {duration_s:.1f}s" if duration_s else ""
        lines = [
            f"── SSE Response Stream ({len(events)} events{dur_str}) ──",
        ]
        for e in events:
            lines.append(f"data: {e.data}")
        lines.append("")
        lines.append("── Aggregated Response ──")
        lines.append(aggregated or "(empty)")
        return "\n".join(lines)
