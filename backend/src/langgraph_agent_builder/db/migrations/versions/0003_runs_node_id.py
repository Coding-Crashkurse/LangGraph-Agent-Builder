"""v3: runs.node_id — failing node stored on the run (SPEC §5.6)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # fresh databases get the column from 0001's create_all baseline
    cols = {c["name"] for c in insp.get_columns("runs")}
    if "node_id" not in cols:
        op.add_column("runs", sa.Column("node_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("runs")}
    if "node_id" in cols:
        op.drop_column("runs", "node_id")
