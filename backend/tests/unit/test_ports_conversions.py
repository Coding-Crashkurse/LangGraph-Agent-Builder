"""Unit tests for lga.sdk.ports payload conversions & the edge-compat internals.

Covers the branches left uncovered by tests/test_ports.py and test_coerce.py:
- Message <-> LangChain BaseMessage (all four roles, both directions)
- LazyToolset caching/invalidation and resolve_toolsets flattening
- the _structural_subset algorithm's edge branches (empty schemas, missing
  type, type mismatch, nested object/array recursion)
"""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from lga.sdk.ports import (
    LazyToolset,
    Message,
    ToolDef,
    _structural_subset,
    resolve_toolsets,
)


# --------------------------------------------------------------- to_langchain
def test_to_langchain_assistant_is_aimessage() -> None:
    lc = Message(role="assistant", content="hi").to_langchain()
    assert isinstance(lc, AIMessage)
    assert lc.content == "hi"


def test_to_langchain_system_is_systemmessage() -> None:
    lc = Message(role="system", content="be nice").to_langchain()
    assert isinstance(lc, SystemMessage)
    assert lc.content == "be nice"


def test_to_langchain_tool_carries_tool_call_id() -> None:
    lc = Message(role="tool", content="42", metadata={"tool_call_id": "call-7"}).to_langchain()
    assert isinstance(lc, ToolMessage)
    assert lc.tool_call_id == "call-7"


def test_to_langchain_user_is_humanmessage_with_name_and_metadata() -> None:
    lc = Message(role="user", content="yo", name="alice", metadata={"k": "v"}).to_langchain()
    assert isinstance(lc, HumanMessage)
    assert lc.name == "alice"
    assert lc.additional_kwargs["lga_metadata"] == {"k": "v"}


# ------------------------------------------------------------- from_langchain
def test_from_langchain_returns_message_unchanged() -> None:
    original = Message(role="assistant", content="same")
    assert Message.from_langchain(original) is original


def test_from_langchain_ai_becomes_assistant() -> None:
    msg = Message.from_langchain(AIMessage(content="done"))
    assert msg.role == "assistant"
    assert msg.content == "done"


def test_from_langchain_system_and_tool_roles() -> None:
    assert Message.from_langchain(SystemMessage(content="s")).role == "system"
    tool = Message.from_langchain(ToolMessage(content="t", tool_call_id="x"))
    assert tool.role == "tool"


def test_from_langchain_human_default_role_and_metadata() -> None:
    msg = Message.from_langchain(
        HumanMessage(content="hey", additional_kwargs={"lga_metadata": {"src": "u"}})
    )
    assert msg.role == "user"
    assert msg.metadata == {"src": "u"}


def test_from_langchain_stringifies_list_content() -> None:
    msg = Message.from_langchain(HumanMessage(content=["a", "b"]))
    assert msg.content == str(["a", "b"])
    assert isinstance(msg.content, str)


def test_message_roundtrip_through_langchain() -> None:
    src = Message(role="tool", content="c", metadata={"tool_call_id": "id1"})
    back = Message.from_langchain(src.to_langchain())
    assert back.role == "tool"
    assert back.content == "c"


# --------------------------------------------------------------- LazyToolset
async def test_lazy_toolset_resolves_and_caches() -> None:
    calls: list[int] = []

    async def factory() -> list[ToolDef]:
        calls.append(1)
        return [ToolDef(name="alpha"), ToolDef(name="beta")]

    lazy = LazyToolset(factory)
    first = await lazy.resolve()
    second = await lazy.resolve()

    assert [t.name for t in first] == ["alpha", "beta"]
    assert second == first
    assert calls == [1]  # factory ran exactly once (cached)


async def test_lazy_toolset_invalidate_forces_refetch() -> None:
    calls: list[int] = []

    async def factory() -> list[ToolDef]:
        calls.append(1)
        return [ToolDef(name="t")]

    lazy = LazyToolset(factory)
    await lazy.resolve()
    lazy.invalidate()
    await lazy.resolve()
    assert calls == [1, 1]  # two invocations


async def test_resolve_toolsets_flattens_mixed_and_empty() -> None:
    async def factory() -> list[ToolDef]:
        return [ToolDef(name="lazy-1")]

    concrete = ToolDef(name="concrete")
    out = await resolve_toolsets([concrete, LazyToolset(factory)])
    assert [t.name for t in out] == ["concrete", "lazy-1"]
    assert await resolve_toolsets([]) == []


# ------------------------------------------------------- _structural_subset
def test_structural_subset_empty_target_accepts_anything() -> None:
    assert _structural_subset({"type": "string"}, {}) is True


def test_structural_subset_empty_source_rejected_by_concrete_target() -> None:
    assert _structural_subset({}, {"type": "object"}) is False


def test_structural_subset_target_without_type_accepts() -> None:
    assert _structural_subset({"type": "string"}, {"properties": {"a": {}}}) is True


def test_structural_subset_type_mismatch_rejected() -> None:
    assert _structural_subset({"type": "string"}, {"type": "object"}) is False


def test_structural_subset_object_required_property_mismatch() -> None:
    source = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }
    target = {
        "type": "object",
        "properties": {"id": {"type": "object"}},
        "required": ["id"],
    }
    # `id` exists in source but string is not a subset of the object target
    assert _structural_subset(source, target) is False


def test_structural_subset_nested_array_recursion() -> None:
    array_str = {"type": "array", "items": {"type": "string"}}
    assert _structural_subset(array_str, array_str) is True
    assert (
        _structural_subset(
            {"type": "array", "items": {"type": "string"}},
            {"type": "array", "items": {"type": "object"}},
        )
        is False
    )


def test_structural_subset_scalar_same_type_accepts() -> None:
    # non-object, non-array, matching type falls through to the final True
    assert _structural_subset({"type": "integer"}, {"type": "integer"}) is True
