from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Auth / Credentials
# ---------------------------------------------------------------------------

class Credentials(BaseModel):
    auth_type: Literal["form", "basic", "bearer", "cookie"]
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    cookies: Optional[dict[str, str]] = None
    login_url: Optional[str] = None
    username_selector: Optional[str] = None
    password_selector: Optional[str] = None
    submit_selector: Optional[str] = None


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

class ProbeTask(BaseModel):
    """Active probe task definition."""
    task_id: str = Field(default_factory=lambda: f"probe-{uuid4().hex[:12]}")

    # Target
    urls: list[str]
    credentials: Optional[Credentials] = None

    # Interaction
    interaction_mode: Literal["auto", "script"] = "auto"
    playwright_script: Optional[str] = None

    # Capture
    capture_timeout: int = 120
    capture_body: bool = True
    max_body_size: int = 10 * 1024 * 1024

    # Output
    output_format: Literal["markdown", "docx", "json"] = "markdown"


class PcapImportConfig(BaseModel):
    """PCAP import task configuration."""
    task_id: str = Field(default_factory=lambda: f"pcap-{uuid4().hex[:12]}")
    filepath: str
    sslkeylog: Optional[str] = None
    output_format: Literal["markdown", "docx", "json"] = "markdown"


# ---------------------------------------------------------------------------
# Capture task (persisted entity)
# ---------------------------------------------------------------------------

class CaptureTask(BaseModel):
    id: str
    type: Literal["active_probe", "pcap_import"]
    status: Literal["pending", "running", "completed", "failed"]
    config: dict[str, Any]
    created_at: datetime
    completed_at: Optional[datetime] = None
    record_count: int = 0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Metadata types
# ---------------------------------------------------------------------------

class FileUploadInfo(BaseModel):
    filename: str
    size: int
    content_type: str
    sha256: Optional[str] = None


class AIMetadata(BaseModel):
    provider: str
    model_name: Optional[str] = None
    api_version: Optional[str] = None
    user_agent: str = ""
    client_version: Optional[str] = None
    app_version: Optional[str] = None
    platform: Optional[str] = None
    auth_type: str = "unknown"
    is_streaming: bool = False
    thinking_enabled: Optional[bool] = None
    file_upload: Optional[FileUploadInfo] = None
    custom_headers: dict[str, str] = Field(default_factory=dict)
    timestamp: Optional[datetime] = None


# ---------------------------------------------------------------------------
# AI Traffic Record
# ---------------------------------------------------------------------------

class AITrafficRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"rec-{uuid4().hex[:12]}")
    task_id: str
    sequence: int

    provider: str
    service_type: str  # chat / completion / embedding / upload / image
    confidence: float

    # Raw packets
    raw_request: str
    raw_response: Optional[str] = None

    # Structured
    method: str
    url: str
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: Optional[str] = None
    response_status: Optional[int] = None
    response_headers: Optional[dict[str, str]] = None
    response_body: Optional[str] = None

    # Metadata
    metadata: AIMetadata

    # Streaming
    stream_type: Optional[Literal["sse", "websocket"]] = None
    stream_events: Optional[list[dict]] = None
    aggregated_response: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# WebSocket / SSE internal types
# ---------------------------------------------------------------------------

class WSFrame(BaseModel):
    payload: bytes
    opcode: int
    direction: Literal["client", "server"]
    timestamp: datetime
    fin: bool = True


class WSMessage(BaseModel):
    conn_id: str
    opcode: int
    payload: bytes
    timestamp_start: datetime
    timestamp_end: datetime
    direction: Literal["client", "server"]


class SSEEvent(BaseModel):
    event_type: str = "message"
    data: str = ""
    event_id: Optional[str] = None
    retry: Optional[int] = None


# ---------------------------------------------------------------------------
# API request/response schemas
# ---------------------------------------------------------------------------

class CreateProbeTaskRequest(BaseModel):
    urls: list[str]
    credentials: Optional[Credentials] = None
    interaction_mode: Literal["auto", "script"] = "auto"
    playwright_script: Optional[str] = None
    capture_timeout: int = 120
    output_format: Literal["markdown", "docx", "json"] = "markdown"


class TaskStatusResponse(BaseModel):
    task_id: str
    type: str
    status: str
    record_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class RecordSummary(BaseModel):
    id: str
    task_id: str
    sequence: int
    provider: str
    service_type: str
    confidence: float
    method: str
    url: str
    response_status: Optional[int] = None
    stream_type: Optional[str] = None
    timestamp: datetime


class LiveMessage(BaseModel):
    type: Literal["new_record", "task_update", "error"]
    task_id: str
    data: dict[str, Any]
