"""Our own tables (alembic-managed). A2A task store, langgraph checkpoints and
pgvector tables are owned by their libraries — see CLAUDE.md §11."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    # {"nodes": [...], "edges": [...]} — see compiler/spec.py
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    agent_card: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    mcp_tool: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    publish_a2a: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_mcp: Mapped[bool] = mapped_column(Boolean, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskEventRow(Base):
    """Persisted debug events; feeds SSE replay (`Last-Event-ID`) + live tail."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID, sortable
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    source: Mapped[str] = mapped_column(String(10))  # a2a | mcp | system
    type: Mapped[str] = mapped_column(String(80))
    node: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunRow(Base):
    """One row per execution (A2A task or MCP tool call) for the debug dashboard."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # a2a task id / mcp run id
    flow_id: Mapped[str] = mapped_column(String(36), index=True)
    context_id: Mapped[str] = mapped_column(String(64))  # == langgraph thread_id
    source: Mapped[str] = mapped_column(String(10))  # a2a | mcp
    state: Mapped[str] = mapped_column(String(20), default="submitted")
    input_preview: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
