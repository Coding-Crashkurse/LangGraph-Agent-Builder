"""Files service (SPEC §9.6): local-disk storage, tokened access URLs."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import FileRow
from lga.errors import LgaValueError
from lga.services.settings import Settings


class FileTooLargeError(LgaValueError):
    pass


class FilesService:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._sessions = sessions

    @property
    def _dir(self) -> Path:
        assert self._settings.files_dir is not None
        self._settings.files_dir.mkdir(parents=True, exist_ok=True)
        return self._settings.files_dir

    async def save(self, name: str, mime: str, content: bytes) -> dict[str, Any]:
        limit = self._settings.max_file_size_mb * 1024 * 1024  # LGA_MAX_FILE_SIZE_MB
        if len(content) > limit:
            raise FileTooLargeError(
                f"file exceeds {self._settings.max_file_size_mb} MB upload limit"
            )
        token = secrets.token_urlsafe(24)
        row = FileRow(name=name or "upload", mime=mime, size=len(content), path="", token=token)
        async with self._sessions() as session:
            session.add(row)
            await session.flush()
            path = self._dir / row.id
            path.write_bytes(content)
            row.path = str(path)
            await session.commit()
            await session.refresh(row)
        return self.info(row)

    async def get(self, file_id: str, token: str | None = None) -> tuple[FileRow, bytes] | None:
        async with self._sessions() as session:
            row = await session.get(FileRow, file_id)
        if row is None:
            return None
        if token is not None and token != row.token:
            return None
        path = Path(row.path)
        if not path.exists():  # noqa: ASYNC240
            return None
        return row, path.read_bytes()  # noqa: ASYNC240

    async def list(self) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (await session.execute(select(FileRow))).scalars().all()
        return [self.info(r) for r in rows]

    def info(self, row: FileRow) -> dict[str, Any]:
        return {
            "file_id": row.id,
            "name": row.name,
            "mime": row.mime,
            "size": row.size,
            "url": f"{self._settings.host_url}/api/v1/files/{row.id}?token={row.token}",
            "created_at": row.created_at.isoformat(),
        }
