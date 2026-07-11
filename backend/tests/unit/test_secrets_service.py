"""Unit tests for langgraph_agent_builder.services.secrets (SPEC §10.3).

Covers kind switching, delete outcomes, decryption error paths, and the
SnapshotVariablesProvider case-insensitive lookups.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from langgraph_agent_builder.db.models import GlobalVariableRow
from langgraph_agent_builder.services.secrets import SecretsService, SnapshotVariablesProvider

if TYPE_CHECKING:
    from tests.unit.conftest import SqliteStack


async def test_set_switch_generic_to_credential_clears_plain(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("token", "plainval", kind="generic")
    await service.set("token", "secretval", kind="credential")

    async with sessions() as session:
        row = (
            await session.execute(
                select(GlobalVariableRow).where(GlobalVariableRow.name == "token")
            )
        ).scalar_one()
    assert row.kind == "credential"
    assert row.value_plain is None
    assert row.value_encrypted
    assert "secretval" not in row.value_encrypted

    _vars, secrets = await service.snapshot()
    assert secrets["token"] == "secretval"


async def test_set_switch_credential_to_generic_clears_encrypted(
    sqlite_stack: SqliteStack,
) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("thing", "secretval", kind="credential")
    await service.set("thing", "nowplain", kind="generic")

    async with sessions() as session:
        row = (
            await session.execute(
                select(GlobalVariableRow).where(GlobalVariableRow.name == "thing")
            )
        ).scalar_one()
    assert row.kind == "generic"
    assert row.value_encrypted is None
    assert row.value_plain == "nowplain"

    variables, _secrets = await service.snapshot()
    assert variables["thing"] == "nowplain"


async def test_delete_returns_true_then_false(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("gone", "x", kind="generic")
    assert await service.delete("gone") is True
    # second delete finds nothing
    assert await service.delete("gone") is False


async def test_snapshot_skips_credential_with_no_ciphertext(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    # a credential row that was never given a value: value_encrypted stays None
    async with sessions() as session:
        session.add(GlobalVariableRow(name="empty_cred", kind="credential"))
        await session.commit()

    _vars, secrets = await service.snapshot()
    assert "empty_cred" not in secrets


async def test_snapshot_skips_credential_with_bad_key(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("api", "sk-real", kind="credential")

    # a second service with a DIFFERENT fernet key cannot decrypt -> InvalidToken -> skipped
    settings.secret_key = ""
    from cryptography.fernet import Fernet

    settings.secret_key = Fernet.generate_key().decode()
    other = SecretsService(settings, sessions)
    _vars, secrets = await other.snapshot()
    assert "api" not in secrets


async def test_list_returns_metadata_only(sqlite_stack: SqliteStack) -> None:
    settings, sessions = sqlite_stack
    service = SecretsService(settings, sessions)
    await service.set("region", "eu", kind="generic")
    await service.set("apikey", "sk-x", kind="credential")

    listed = {row["name"]: row for row in await service.list()}
    assert listed["region"]["kind"] == "generic"
    assert listed["apikey"]["kind"] == "credential"
    # values (plain or encrypted) are never surfaced through list()
    assert "value" not in listed["apikey"]
    assert "value_plain" not in listed["region"]
    assert "created_at" in listed["region"]
    assert "updated_at" in listed["region"]


async def test_snapshot_env_promotion(
    sqlite_stack: SqliteStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sessions = sqlite_stack
    monkeypatch.setenv("LAB_VAR_TENANT", "acme")
    monkeypatch.setenv("LAB_CRED_STRIPE_KEY", "sk-stripe")
    service = SecretsService(settings, sessions)
    variables, secrets = await service.snapshot()
    # promoted under both original-cased and lowercased names
    assert variables["tenant"] == "acme"
    assert variables["TENANT"] == "acme"
    assert secrets["stripe_key"] == "sk-stripe"
    assert secrets["STRIPE_KEY"] == "sk-stripe"


async def test_provider_case_insensitive_lookup() -> None:
    # values stored lowercase; queries in mixed case must still resolve
    provider = SnapshotVariablesProvider({"region": "eu"}, {"openai_key": "sk-1"})
    # exact hit
    assert provider.get_var("region") == "eu"
    # lowercase fallback for an upper-cased query
    assert provider.get_var("REGION") == "eu"
    assert provider.get_secret("OPENAI_KEY") == "sk-1"
    assert provider.has_secret("OPENAI_KEY") is True
    assert provider.has_var("REGION") is True
    assert provider.has_var("nope") is False
    assert provider.has_secret("nope") is False
    assert provider.get_var("missing") is None
    assert provider.get_secret("missing") is None
