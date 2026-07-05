"""Fixed state schema for all flows in the PoC (CLAUDE.md §8, decision #2)."""

from typing import Annotated, Any

from langchain_core.documents import Document
from langgraph.graph import MessagesState


def merge_data(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge reducer for the `data` channel."""
    return {**(left or {}), **(right or {})}


class FlowState(MessagesState):
    documents: list[Document]  # last-write-wins
    route: str | None  # router scratch, last-write-wins
    data: Annotated[dict[str, Any], merge_data]


FLOW_STATE_KEYS = frozenset({"messages", "documents", "route", "data"})
