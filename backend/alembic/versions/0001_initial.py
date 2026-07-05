"""initial: flows, task_events, runs

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("graph", JSONB(), nullable=False, server_default="{}"),
        sa.Column("agent_card", JSONB(), nullable=True),
        sa.Column("mcp_tool", JSONB(), nullable=True),
        sa.Column("publish_a2a", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("publish_mcp", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_published", sa.Boolean(), nullable=False, server_default=sa.false(), index=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "task_events",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False, index=True),
        sa.Column("flow_id", sa.String(36), nullable=False, index=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("node", sa.String(80), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("flow_id", sa.String(36), nullable=False, index=True),
        sa.Column("context_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="submitted"),
        sa.Column("input_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("runs")
    op.drop_table("task_events")
    op.drop_table("flows")
