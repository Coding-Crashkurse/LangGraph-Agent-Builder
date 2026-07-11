"""Service-level tests: secrets (write-only creds), push SSRF/delivery, files."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from langgraph_agent_builder.a2a.push import (
    DbPushConfigStore,
    GuardedPushSender,
    SsrfError,
    validate_webhook_url,
)
from langgraph_agent_builder.services.secrets import SecretsService, SnapshotVariablesProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from langgraph_agent_builder.services.settings import Settings

SqliteStack = tuple["Settings", "async_sessionmaker[AsyncSession]"]


@pytest.fixture
async def sqlite_stack(sqlite_settings: Settings) -> AsyncIterator[SqliteStack]:
    from langgraph_agent_builder.db.migrate import upgrade_async
    from langgraph_agent_builder.services.db import create_engine, create_sessionmaker

    await upgrade_async(sqlite_settings)
    engine = create_engine(sqlite_settings)
    sessions = create_sessionmaker(engine)
    yield sqlite_settings, sessions
    await engine.dispose()


# ------------------------------------------------------------------ secrets (§10.3)
async def test_credentials_encrypted_and_write_only(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("openai_key", "sk-secret", kind="credential")
    await service.set("region", "eu-west", kind="generic")

    listed = await service.list()
    by_name = {v["name"]: v for v in listed}
    assert by_name["openai_key"]["kind"] == "credential"
    assert "value" not in by_name["openai_key"]  # write-only, never echoed

    # raw row must not contain the plaintext
    from sqlalchemy import select

    from langgraph_agent_builder.db.models import GlobalVariableRow

    async with sessions() as session:
        row = (
            await session.execute(
                select(GlobalVariableRow).where(GlobalVariableRow.name == "openai_key")
            )
        ).scalar_one()
    assert row.value_plain is None
    assert row.value_encrypted
    assert "sk-secret" not in row.value_encrypted

    variables, secrets = await service.snapshot()
    assert variables["region"] == "eu-west"
    assert secrets["openai_key"] == "sk-secret"

    provider = SnapshotVariablesProvider(variables, secrets)
    assert provider.get_secret("openai_key") == "sk-secret"
    assert provider.has_var("region")
    assert not provider.has_var("missing")


async def test_env_promotion(sqlite_stack: SqliteStack, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, sessions = sqlite_stack
    monkeypatch.setenv("LAB_VAR_TENANT", "acme")
    monkeypatch.setenv("LAB_CRED_STRIPE_KEY", "sk-stripe")
    service = SecretsService(settings, sessions)
    variables, secrets = await service.snapshot()
    assert variables["tenant"] == "acme"
    assert secrets["stripe_key"] == "sk-stripe"


# ------------------------------------------------------------------ push (§7.9)
def test_ssrf_validation(sqlite_settings: Settings) -> None:
    validate_webhook_url("https://example.com/hook", sqlite_settings)
    with pytest.raises(SsrfError):
        validate_webhook_url("http://127.0.0.1:9/hook", sqlite_settings)
    with pytest.raises(SsrfError):
        validate_webhook_url("http://192.168.1.5/hook", sqlite_settings)
    with pytest.raises(SsrfError):
        validate_webhook_url("ftp://example.com/x", sqlite_settings)
    sqlite_settings.push_allow_private = True
    validate_webhook_url("http://127.0.0.1:9/hook", sqlite_settings)  # dev escape hatch


async def test_push_delivery_with_token_and_retry(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    settings.push_allow_private = True
    store = DbPushConfigStore(sessions, settings)

    from a2a.types import (
        Message,
        Part,
        PushNotificationConfig,
        Role,
        Task,
        TaskState,
        TaskStatus,
        TextPart,
    )

    task = Task(
        id="pt1",
        context_id="pc1",
        status=TaskStatus(state=TaskState.completed),
        history=[Message(role=Role.user, message_id="m1", parts=[Part(root=TextPart(text="x"))])],
    )
    await store.set_info(
        "pt1", PushNotificationConfig(id="c1", url="http://10.0.0.5/hook", token="tok-123")
    )

    calls: list[httpx.Request] = []
    fail_first = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        fail_first["n"] += 1
        if fail_first["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    sender = GuardedPushSender(client, store, settings)
    await sender.send_notification(task)
    assert len(calls) == 2  # retried after the 500
    assert calls[-1].headers["X-A2A-Notification-Token"] == "tok-123"
    import json

    payload = json.loads(calls[-1].content)
    assert payload["id"] == "pt1"
    assert payload["status"]["state"] == "completed"
    await client.aclose()


async def test_push_blocked_for_private_url_by_default(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    store = DbPushConfigStore(sessions, settings)
    from a2a.types import PushNotificationConfig

    with pytest.raises(SsrfError):
        await store.set_info("px", PushNotificationConfig(id="c", url="http://192.168.0.1/hook"))


# ------------------------------------------------------------------ files (§9.6)
async def test_files_roundtrip(sqlite_stack: SqliteStack) -> None:
    from langgraph_agent_builder.services.files import FilesService

    settings, sessions = sqlite_stack
    service = FilesService(settings, sessions)
    info = await service.save("notes.txt", "text/plain", b"hello files")
    assert info["size"] == 11
    assert "token=" in info["url"]
    found = await service.get(info["file_id"])
    assert found is not None
    row, content = found
    assert content == b"hello files"
    # wrong token → denied
    assert await service.get(info["file_id"], token="wrong") is None
    assert await service.get(info["file_id"], token=row.token) is not None
