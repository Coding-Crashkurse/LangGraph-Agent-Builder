"""v6: a2a_tasks.protocol_version — a2a-sdk 1.x (protocol v1.0)

The a2a-sdk 1.x task/push DB models grew a ``protocol_version`` column; our
custom ``a2a_tasks`` store mirrors it so persisted snapshots record the
negotiated protocol. Fresh databases already get this from 0001's
``create_all`` baseline; this revision covers existing databases and is
column-inspect-guarded so re-running it is a no-op.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_TABLE = "a2a_tasks"
_COLUMN = "protocol_version"


def _has_column(bind: sa.engine.Connection) -> bool:
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return False
    return any(col["name"] == _COLUMN for col in insp.get_columns(_TABLE))


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE) or _has_column(bind):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        return
    op.drop_column(_TABLE, _COLUMN)
