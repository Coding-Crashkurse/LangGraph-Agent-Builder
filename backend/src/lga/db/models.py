"""App tables (SPEC §10.1) — dialect-portable (SQLite + Postgres)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class FlowRow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(sa.String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONVariant)  # draft FlowSpec
    locked: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # SPEC §9.1
    serve_version: Mapped[str] = mapped_column(sa.String(32), default="latest_published")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FlowVersionRow(Base):
    __tablename__ = "flow_versions"
    __table_args__ = (sa.UniqueConstraint("flow_id", "semver", name="uq_flow_semver"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    flow_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey("flows.id", ondelete="CASCADE"), index=True
    )
    semver: Mapped[str] = mapped_column(sa.String(32))
    flowspec: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    changelog: Mapped[str] = mapped_column(sa.Text, default="")
    published_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    flow_id: Mapped[str | None] = mapped_column(sa.String(36), index=True, nullable=True)
    flow_version_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    flow_slug: Mapped[str] = mapped_column(sa.String(100), default="", index=True)
    thread_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    mode: Mapped[str] = mapped_column(sa.String(16), default="api")
    status: Mapped[str] = mapped_column(sa.String(20), default="pending", index=True)
    error_code: Mapped[str | None] = mapped_column(sa.String(10), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    node_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)  # failing node §5.6
    result_preview: Mapped[str] = mapped_column(sa.Text, default="")
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class RunEventRow(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
        sa.Index("ix_run_events_run_seq", "run_id", "seq"),
    )

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[str] = mapped_column(sa.String(36))
    seq: Mapped[int] = mapped_column(sa.Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class A2ATaskRow(Base):
    __tablename__ = "a2a_tasks"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    context_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    flow_slug: Mapped[str] = mapped_column(sa.String(100), index=True)
    state: Mapped[str] = mapped_column(sa.String(24), default="submitted", index=True)
    task: Mapped[dict[str, Any]] = mapped_column(JSONVariant)  # full a2a Task snapshot
    client_scope: Mapped[str] = mapped_column(sa.String(80), default="")  # §7.11 namespacing
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskTransitionRow(Base):
    __tablename__ = "task_transitions"

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    task_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    from_state: Mapped[str] = mapped_column(sa.String(24))
    to_state: Mapped[str] = mapped_column(sa.String(24))
    message: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class PushConfigRow(Base):
    __tablename__ = "push_configs"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    url: Mapped[str] = mapped_column(sa.Text)
    token: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    created_by: Mapped[str] = mapped_column(sa.String(80), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class GlobalVariableRow(Base):
    __tablename__ = "global_variables"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(sa.String(120), unique=True, index=True)
    kind: Mapped[str] = mapped_column(sa.String(16), default="generic")  # generic | credential
    value_plain: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value_encrypted: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    key_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(sa.String(16), default="")  # display: lga_sk_ab…
    scopes: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    total_uses: Mapped[int] = mapped_column(sa.Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class FileRow(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(sa.String(255))
    mime: Mapped[str] = mapped_column(sa.String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(sa.Integer, default=0)
    path: Mapped[str] = mapped_column(sa.Text)
    token: Mapped[str] = mapped_column(sa.String(64), default="")  # presigned-ish access token
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class McpServerRow(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(sa.String(120), unique=True, index=True)
    transport: Mapped[str] = mapped_column(sa.String(24), default="streamable_http")
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VectorStoreConnectionRow(Base):
    """Named, server-managed vector store connection (SPEC §8b.3).

    ``config`` holds ``{backend, params}``; credential params are ``$secret``
    refs — never plaintext. Local backend data lives outside the app DB
    (``LGA_HOME/vectors/*.db``).
    """

    __tablename__ = "vector_store_connections"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(sa.String(120), unique=True, index=True)
    backend: Mapped[str] = mapped_column(sa.String(24), default="local")
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    managed: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # env/auto-provisioned
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
