"""FilesService streaming save + public token gate (SPEC §9.6).

Complements test_files_service.py: the mid-stream size abort (no full-body
buffering, partial file removed) and the get_public gate where an absent or
empty token never matches.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lga.services.files import FilesService, FileTooLargeError

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


async def _chunks(*blocks: bytes) -> AsyncIterator[bytes]:
    for block in blocks:
        yield block


async def test_save_stream_roundtrip(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save_stream("s.txt", "text/plain", _chunks(b"hello ", b"stream"))
    assert info["size"] == 12
    got = await service.get(info["file_id"])
    assert got is not None
    _row, content = got
    assert content == b"hello stream"


async def test_save_stream_aborts_mid_stream_and_cleans_up(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.max_file_size_mb = 0  # limit = 0 bytes → first chunk already exceeds
    service = FilesService(settings, sessions)
    with pytest.raises(FileTooLargeError, match="upload limit"):
        await service.save_stream("big.bin", "application/octet-stream", _chunks(b"x", b"y"))
    # no row committed, no partial file left behind
    assert await service.list() == []
    assert settings.files_dir is not None
    assert list(settings.files_dir.iterdir()) == []


async def test_save_stream_rejects_oversize_hint_before_writing(
    sqlite_stack: SqliteStack,
) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    limit = settings.max_file_size_mb * 1024 * 1024
    with pytest.raises(FileTooLargeError, match="upload limit"):
        await service.save_stream("big.bin", "text/plain", _chunks(b"x"), size_hint=limit + 1)


async def test_get_public_requires_the_exact_token(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("f.txt", "text/plain", b"secret")
    got = await service.get(info["file_id"])
    assert got is not None
    row, _ = got

    # absent/empty token NEVER matches (the old bypass), wrong token denied
    assert await service.get_public(info["file_id"], "") is None
    assert await service.get_public(info["file_id"], "wrong") is None
    found = await service.get_public(info["file_id"], row.token)
    assert found is not None
    assert found.id == info["file_id"]


async def test_get_public_missing_on_disk_is_none(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("f.txt", "text/plain", b"data")
    got = await service.get(info["file_id"])
    assert got is not None
    row, _ = got
    Path(row.path).unlink()  # noqa: ASYNC240 — test setup, not production IO
    assert await service.get_public(info["file_id"], row.token) is None
