"""Records API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from prism import database as db
from prism.models import RecordSummary

router = APIRouter(prefix="/api/v1", tags=["records"])


@router.get("/tasks/{task_id}/records")
async def list_task_records(task_id: str):
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    rows = await db.get_task_records(task_id)
    summaries = []
    for row in rows:
        summaries.append(
            RecordSummary(
                id=row.id,
                task_id=row.task_id,
                sequence=row.sequence,
                provider=row.provider,
                service_type=row.service_type,
                confidence=row.confidence,
                method=row.method,
                url=row.url,
                response_status=row.response_status,
                stream_type=row.stream_type,
                timestamp=row.timestamp,
            )
        )
    return summaries


@router.get("/records/{record_id}")
async def get_record(record_id: str):
    row = await db.get_record(record_id)
    if not row:
        raise HTTPException(404, "Record not found")
    return db.row_to_record_dict(row)
