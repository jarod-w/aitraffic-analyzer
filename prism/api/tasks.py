"""Task API routes — create and manage probe/PCAP tasks."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from prism import database as db
from prism.api.live import live_manager
from prism.config import settings
from prism.models import (
    AITrafficRecord,
    CaptureTask,
    CreateProbeTaskRequest,
    Credentials,
    PcapImportConfig,
    ProbeTask,
    TaskStatusResponse,
)
from prism.report.generator import generate_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["tasks"])


# ---------------------------------------------------------------------------
# Active probe task
# ---------------------------------------------------------------------------

@router.post("/tasks/probe", response_model=TaskStatusResponse, status_code=202)
async def create_probe_task(
    request: CreateProbeTaskRequest,
    background_tasks: BackgroundTasks,
):
    task = ProbeTask(
        urls=request.urls,
        credentials=request.credentials,
        interaction_mode=request.interaction_mode,
        playwright_script=request.playwright_script,
        capture_timeout=request.capture_timeout,
        output_format=request.output_format,
    )

    await db.create_task(task.task_id, "active_probe", task.model_dump())
    background_tasks.add_task(_run_probe_task, task)

    return TaskStatusResponse(
        task_id=task.task_id,
        type="active_probe",
        status="pending",
        record_count=0,
        created_at=datetime.utcnow(),
    )


async def _run_probe_task(task: ProbeTask):
    await db.update_task_status(task.task_id, "running")
    await live_manager.broadcast_task_update(task.task_id, "running", 0)

    records: list[AITrafficRecord] = []
    record_count = 0

    async def on_record(record: AITrafficRecord):
        nonlocal record_count
        record_count += 1
        records.append(record)
        await db.save_record(_record_to_db_dict(record))
        await live_manager.broadcast_record(task.task_id, _record_summary(record))
        await db.update_task_status(task.task_id, "running", record_count=record_count)

    try:
        from prism.capture.probe import ActiveProbe
        probe = ActiveProbe(task, on_record=on_record)
        await probe.run()

        await db.update_task_status(
            task.task_id,
            "completed",
            record_count=record_count,
            completed_at=datetime.utcnow(),
        )
        await live_manager.broadcast_task_update(task.task_id, "completed", record_count)
    except Exception as e:
        logger.exception("Probe task %s failed", task.task_id)
        await db.update_task_status(
            task.task_id,
            "failed",
            record_count=record_count,
            error_message=str(e),
            completed_at=datetime.utcnow(),
        )
        await live_manager.broadcast_task_update(task.task_id, "failed", record_count)


# ---------------------------------------------------------------------------
# PCAP import task
# ---------------------------------------------------------------------------

@router.post("/tasks/pcap", response_model=TaskStatusResponse, status_code=202)
async def create_pcap_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    sslkeylog: Optional[str] = Form(None),
    output_format: str = Form("markdown"),
):
    # Validate extension
    filename = file.filename or "upload.pcap"
    if not filename.endswith((".pcap", ".pcapng")):
        raise HTTPException(400, "Only .pcap / .pcapng files are supported")

    # Save upload
    settings.ensure_dirs()
    dest = settings.uploads_dir / filename
    content = await file.read()

    if len(content) > settings.max_pcap_size:
        raise HTTPException(413, f"File exceeds {settings.max_pcap_size // 1024 // 1024}MB limit")

    dest.write_bytes(content)

    config = PcapImportConfig(
        filepath=str(dest),
        sslkeylog=sslkeylog,
        output_format=output_format,
    )
    await db.create_task(config.task_id, "pcap_import", config.model_dump())
    background_tasks.add_task(_run_pcap_task, config)

    return TaskStatusResponse(
        task_id=config.task_id,
        type="pcap_import",
        status="pending",
        record_count=0,
        created_at=datetime.utcnow(),
    )


async def _run_pcap_task(config: PcapImportConfig):
    await db.update_task_status(config.task_id, "running")
    await live_manager.broadcast_task_update(config.task_id, "running", 0)

    try:
        from prism.pcap.analyzer import PcapAnalyzer

        # Run in thread pool (scapy is blocking)
        loop = asyncio.get_running_loop()
        analyzer = PcapAnalyzer(
            filepath=config.filepath,
            task_id=config.task_id,
            sslkeylog=config.sslkeylog,
        )
        records: list[AITrafficRecord] = await loop.run_in_executor(None, analyzer.parse)

        for record in records:
            await db.save_record(_record_to_db_dict(record))
            await live_manager.broadcast_record(config.task_id, _record_summary(record))

        await db.update_task_status(
            config.task_id,
            "completed",
            record_count=len(records),
            completed_at=datetime.utcnow(),
        )
        await live_manager.broadcast_task_update(config.task_id, "completed", len(records))

    except Exception as e:
        logger.exception("PCAP task %s failed", config.task_id)
        await db.update_task_status(
            config.task_id,
            "failed",
            error_message=str(e),
            completed_at=datetime.utcnow(),
        )
        await live_manager.broadcast_task_update(config.task_id, "failed", 0)


# ---------------------------------------------------------------------------
# Task query
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str):
    row = await db.get_task(task_id)
    if not row:
        raise HTTPException(404, "Task not found")
    return TaskStatusResponse(
        task_id=row.id,
        type=row.type,
        status=row.status,
        record_count=row.record_count,
        created_at=row.created_at,
        completed_at=row.completed_at,
        error_message=row.error_message,
    )


# ---------------------------------------------------------------------------
# Report download
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/report")
async def download_report(task_id: str, format: str = "markdown"):
    if format not in ("markdown", "docx", "json"):
        raise HTTPException(400, "format must be markdown, docx, or json")

    row = await db.get_task(task_id)
    if not row:
        raise HTTPException(404, "Task not found")

    record_rows = await db.get_task_records(task_id)
    records = [_row_to_record(r) for r in record_rows]

    content, content_type = generate_report(task_id, records, fmt=format)

    ext = {"markdown": "md", "docx": "docx", "json": "json"}[format]
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="prism-{task_id}.{ext}"'},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_to_db_dict(record: AITrafficRecord) -> dict:
    d = record.model_dump()
    d["metadata"] = d["metadata"]
    return d


def _record_summary(record: AITrafficRecord) -> dict:
    return {
        "id": record.id,
        "provider": record.provider,
        "url": record.url,
        "method": record.method,
        "service_type": record.service_type,
        "confidence": record.confidence,
        "response_status": record.response_status,
        "stream_type": record.stream_type,
        "metadata": {
            "model_name": record.metadata.model_name,
            "file_upload": record.metadata.file_upload.model_dump() if record.metadata.file_upload else None,
        },
    }


def _row_to_record(row) -> AITrafficRecord:
    d = db.row_to_record_dict(row)
    # Reconstruct nested models
    meta_dict = d.pop("metadata", {})
    if "file_upload" in meta_dict and meta_dict["file_upload"]:
        from prism.models import FileUploadInfo
        meta_dict["file_upload"] = FileUploadInfo(**meta_dict["file_upload"])
    from prism.models import AIMetadata
    d["metadata"] = AIMetadata(**meta_dict)
    return AITrafficRecord(**d)
