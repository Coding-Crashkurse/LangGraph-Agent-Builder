"""v5: node_runs — per-node run timeline (REFACTOR.md §7)

One row per (run, node, iteration) captured from the compiler node wrapper so
every run is fully inspectable. Fresh databases already get this from 0001's
``create_all`` baseline; this revision covers existing databases.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("node_runs"):
        return
    op.create_table(
        "node_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("input_snapshot", JSONVariant, nullable=True),
        sa.Column("output_snapshot", JSONVariant, nullable=True),
        sa.Column("tokens", sa.Integer, nullable=True),
        sa.Column("cost", sa.Float, nullable=True),
        sa.Column("error_code", sa.String(length=16), nullable=True),
    )
    op.create_index("ix_node_runs_run_id", "node_runs", ["run_id"])
    op.create_index("ix_node_runs_run_node_iter", "node_runs", ["run_id", "node_id", "iteration"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("node_runs"):
        return
    op.drop_index("ix_node_runs_run_node_iter", table_name="node_runs")
    op.drop_index("ix_node_runs_run_id", table_name="node_runs")
    op.drop_table("node_runs")
