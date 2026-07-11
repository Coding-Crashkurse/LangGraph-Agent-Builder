"""v2: flows.locked + vector_store_connections (SPEC §8b.3, §9.1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    cols = {c["name"] for c in insp.get_columns("flows")}
    if "locked" not in cols:
        op.add_column(
            "flows",
            sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if not insp.has_table("vector_store_connections"):
        op.create_table(
            "vector_store_connections",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("backend", sa.String(length=24), nullable=False, server_default="local"),
            sa.Column("config", JSONVariant, nullable=False),
            sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_vector_store_connections_name",
            "vector_store_connections",
            ["name"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("vector_store_connections"):
        op.drop_index("ix_vector_store_connections_name", table_name="vector_store_connections")
        op.drop_table("vector_store_connections")
    cols = {c["name"] for c in insp.get_columns("flows")}
    if "locked" in cols:
        op.drop_column("flows", "locked")
