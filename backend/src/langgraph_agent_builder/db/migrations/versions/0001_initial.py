"""initial schema — all app tables (SPEC §10.1)

Revision ID: 0001
Revises:
Create Date: 2026-07-05
"""

from alembic import op

from langgraph_agent_builder.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # v1 baseline intentionally mirrors the declarative models 1:1.
    # Subsequent revisions must use explicit op.* calls (autogenerate is banned).
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
