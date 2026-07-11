"""v4: resources layer — model_providers + knowledge_bases + a2a_agents

Long-lived, panel-managed config referenced by {"$resource": name}. The
``mcp_server`` resource type reuses the existing ``mcp_servers`` table, so only
three new tables are created here. Fresh databases already get these from
0001's ``create_all`` baseline; this revision covers existing databases.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")

_TABLES = ("model_providers", "knowledge_bases", "a2a_agents")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in _TABLES:
        if insp.has_table(table):
            continue
        op.create_table(
            table,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("config", JSONVariant, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(f"ix_{table}_name", table, ["name"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in _TABLES:
        if not insp.has_table(table):
            continue
        op.drop_index(f"ix_{table}_name", table_name=table)
        op.drop_table(table)
