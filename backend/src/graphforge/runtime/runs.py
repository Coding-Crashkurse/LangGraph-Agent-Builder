"""Run log: mirrors every execution (A2A task / MCP tool call) into the `runs`
table so the debug dashboard has one uniform task list."""

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graphforge.db.models import RunRow

logger = logging.getLogger(__name__)


class RunLog:
    """No-op when constructed without a sessionmaker (in-memory tests)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None) -> None:
        self._sessionmaker = sessionmaker

    async def upsert(
        self,
        *,
        run_id: str,
        flow_id: str,
        context_id: str,
        source: str,
        state: str,
        input_preview: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._sessionmaker is None:
            return
        values: dict[str, object] = {
            "flow_id": flow_id,
            "context_id": context_id,
            "source": source,
            "state": state,
        }
        if input_preview is not None:
            values["input_preview"] = input_preview[:500]
        if error is not None:
            values["error"] = error[:2000]
        try:
            async with self._sessionmaker() as session:
                stmt = insert(RunRow).values(id=run_id, **values)
                stmt = stmt.on_conflict_do_update(index_elements=[RunRow.id], set_=values)
                await session.execute(stmt)
                await session.commit()
        except Exception:  # bookkeeping must never break a run
            logger.exception("failed to upsert run %s", run_id)
