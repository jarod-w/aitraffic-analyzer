"""SQLite (or PostgreSQL) persistence layer using SQLAlchemy async."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from prism.config import settings


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    record_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)


class RecordRow(Base):
    __tablename__ = "records"

    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    provider = Column(String, nullable=False)
    service_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    method = Column(String, nullable=False)
    url = Column(Text, nullable=False)
    request_headers_json = Column(Text, nullable=False, default="{}")
    request_body = Column(Text, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_headers_json = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    raw_request = Column(Text, nullable=False)
    raw_response = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    stream_type = Column(String, nullable=True)
    stream_events_json = Column(Text, nullable=True)
    aggregated_response = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------

_engine = create_async_engine(settings.effective_db_url, echo=settings.debug)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    return _session_factory()


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

async def create_task(task_id: str, task_type: str, config: dict) -> TaskRow:
    async with get_session() as session:
        row = TaskRow(
            id=task_id,
            type=task_type,
            status="pending",
            config_json=json.dumps(config),
            created_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()
        return row


async def get_task(task_id: str) -> Optional[TaskRow]:
    async with get_session() as session:
        result = await session.execute(select(TaskRow).where(TaskRow.id == task_id))
        return result.scalar_one_or_none()


async def update_task_status(
    task_id: str,
    status: str,
    record_count: int = 0,
    error_message: Optional[str] = None,
    completed_at: Optional[datetime] = None,
):
    async with get_session() as session:
        values: dict[str, Any] = {"status": status, "record_count": record_count}
        if error_message is not None:
            values["error_message"] = error_message
        if completed_at is not None:
            values["completed_at"] = completed_at
        await session.execute(update(TaskRow).where(TaskRow.id == task_id).values(**values))
        await session.commit()


async def save_record(record_data: dict) -> RecordRow:
    async with get_session() as session:
        row = RecordRow(
            id=record_data["id"],
            task_id=record_data["task_id"],
            sequence=record_data["sequence"],
            provider=record_data["provider"],
            service_type=record_data["service_type"],
            confidence=record_data["confidence"],
            method=record_data["method"],
            url=record_data["url"],
            request_headers_json=json.dumps(record_data.get("request_headers", {})),
            request_body=record_data.get("request_body"),
            response_status=record_data.get("response_status"),
            response_headers_json=json.dumps(record_data.get("response_headers") or {}),
            response_body=record_data.get("response_body"),
            raw_request=record_data["raw_request"],
            raw_response=record_data.get("raw_response"),
            metadata_json=json.dumps(record_data.get("metadata", {})),
            stream_type=record_data.get("stream_type"),
            stream_events_json=json.dumps(record_data.get("stream_events") or []),
            aggregated_response=record_data.get("aggregated_response"),
            timestamp=record_data.get("timestamp", datetime.utcnow()),
        )
        session.add(row)
        await session.commit()
        return row


async def get_task_records(task_id: str) -> list[RecordRow]:
    async with get_session() as session:
        result = await session.execute(
            select(RecordRow)
            .where(RecordRow.task_id == task_id)
            .order_by(RecordRow.sequence)
        )
        return list(result.scalars().all())


async def get_record(record_id: str) -> Optional[RecordRow]:
    async with get_session() as session:
        result = await session.execute(
            select(RecordRow).where(RecordRow.id == record_id)
        )
        return result.scalar_one_or_none()


def row_to_record_dict(row: RecordRow) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "sequence": row.sequence,
        "provider": row.provider,
        "service_type": row.service_type,
        "confidence": row.confidence,
        "method": row.method,
        "url": row.url,
        "request_headers": json.loads(row.request_headers_json or "{}"),
        "request_body": row.request_body,
        "response_status": row.response_status,
        "response_headers": json.loads(row.response_headers_json or "{}"),
        "response_body": row.response_body,
        "raw_request": row.raw_request,
        "raw_response": row.raw_response,
        "metadata": json.loads(row.metadata_json or "{}"),
        "stream_type": row.stream_type,
        "stream_events": json.loads(row.stream_events_json or "[]"),
        "aggregated_response": row.aggregated_response,
        "timestamp": row.timestamp,
    }
