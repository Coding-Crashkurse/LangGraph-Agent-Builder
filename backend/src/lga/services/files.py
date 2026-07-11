"""Files service (SPEC §9.6): local-disk storage, tokened access URLs."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import FileRow
from lga.errors import LgaValueError
from lga.services.settings import Settings

CHUNK_SIZE = 1024 * 1024


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

    @property
    def _limit_bytes(self) -> int:
        return self._settings.max_file_size_mb * 1024 * 1024  # LGA_MAX_FILE_SIZE_MB

    def _too_large(self) -> FileTooLargeError:
        return FileTooLargeError(f"file exceeds {self._settings.max_file_size_mb} MB upload limit")

    async def save(self, name: str, mime: str, content: bytes) -> dict[str, Any]:
        if len(content) > self._limit_bytes:
            raise self._too_large()

        async def one_chunk() -> AsyncIterator[bytes]:
            yield content

        return await self.save_stream(name, mime, one_chunk())

    async def save_stream(
        self, name: str, mime: str, chunks: AsyncIterator[bytes], *, size_hint: int | None = None
    ) -> dict[str, Any]:
        """Stream an upload to disk, enforcing the size limit mid-stream (§9.6).

        The body is never buffered whole: chunks go straight to the target file
        (disk IO off the event loop) and the write aborts — removing the partial
        file, rolling back the row — the moment the running total exceeds the
        limit. ``size_hint`` (Content-Length) rejects oversized uploads early.
        """
        limit = self._limit_bytes
        if size_hint is not None and size_hint > limit:
            raise self._too_large()
        token = secrets.token_urlsafe(24)
        row = FileRow(name=name or "upload", mime=mime, size=0, path="", token=token)
        async with self._sessions() as session:
            session.add(row)
            await session.flush()
            path = self._dir / row.id
            size = 0
            try:
                handle = await asyncio.to_thread(path.open, "wb")
                try:
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > limit:
                            raise self._too_large()
                        await asyncio.to_thread(handle.write, chunk)
                finally:
                    await asyncio.to_thread(handle.close)
            except BaseException:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(path.unlink)
                raise  # session context closes uncommitted → row insert rolls back
            row.size = size
            row.path = str(path)
            await session.commit()
            await session.refresh(row)
        return self.info(row)

    async def get(self, file_id: str, token: str | None = None) -> tuple[FileRow, bytes] | None:
        """Trusted server-side lookup (run inputs, RAG components).

        ``token=None`` skips the token check — this method must never back a
        public route; use :meth:`get_public` for the tokened download URL.
        """
        async with self._sessions() as session:
            row = await session.get(FileRow, file_id)
        if row is None:
            return None
        if token is not None and token != row.token:
            return None
        path = Path(row.path)
        if not await asyncio.to_thread(path.exists):
            return None
        return row, await asyncio.to_thread(path.read_bytes)

    async def get_public(self, file_id: str, token: str) -> FileRow | None:
        """Token-gated lookup for the public download URL (SPEC §9.6).

        An absent or empty token NEVER matches — the per-file token is the only
        credential on this route, so it is required, not optional.
        """
        if not token:
            return None
        async with self._sessions() as session:
            row = await session.get(FileRow, file_id)
        if row is None or not row.token or token != row.token:
            return None
        if not await asyncio.to_thread(Path(row.path).exists):
            return None
        return row

    async def list(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        stmt = select(FileRow).order_by(FileRow.created_at.desc()).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
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
