"""Unit tests for lga.services.files (SPEC §9.6).

Covers the size-limit error path, default naming, token gating, and the
missing-file-on-disk branch.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lga.services.files import FilesService, FileTooLargeError

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


async def test_save_roundtrip_and_info(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("notes.txt", "text/plain", b"hello files")
    assert info["size"] == 11
    assert info["name"] == "notes.txt"
    assert info["mime"] == "text/plain"
    assert info["url"].startswith(settings.host_url)
    assert "token=" in info["url"]

    listed = await service.list()
    assert [row["file_id"] for row in listed] == [info["file_id"]]


async def test_save_rejects_oversize(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.max_file_size_mb = 0  # nothing may be uploaded
    service = FilesService(settings, sessions)
    with pytest.raises(FileTooLargeError, match="upload limit"):
        await service.save("big.bin", "application/octet-stream", b"x")


async def test_save_defaults_empty_name(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("", "text/plain", b"data")
    assert info["name"] == "upload"


async def test_get_missing_id_returns_none(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    assert await service.get("00000000-0000-0000-0000-000000000000") is None


async def test_get_token_gate(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("f.txt", "text/plain", b"secret")

    # no token supplied -> allowed (token=None bypasses the check)
    got = await service.get(info["file_id"])
    assert got is not None
    row, content = got
    assert content == b"secret"

    # wrong token -> denied
    assert await service.get(info["file_id"], token="wrong") is None
    # right token -> allowed
    assert await service.get(info["file_id"], token=row.token) is not None


async def test_get_missing_on_disk_returns_none(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("f.txt", "text/plain", b"data")

    # row exists in DB but the backing file is gone from disk
    got = await service.get(info["file_id"])
    assert got is not None
    row, _content = got
    Path(row.path).unlink()  # noqa: ASYNC240

    assert await service.get(info["file_id"]) is None
