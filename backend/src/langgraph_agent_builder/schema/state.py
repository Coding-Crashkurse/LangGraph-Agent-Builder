"""FlowState — the one shared LangGraph state schema (SPEC §5.1)."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_data(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow dict merge, key-level last-write-wins.

    Same-superstep write conflicts (RT101) are detected by the executor, which
    sees per-superstep update chunks; a reducer only ever sees pairwise merges.
    """
    return {**(old or {}), **(new or {})}


def merge_keyed(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """Key-level merge for the namespaced `ports` / `route` channels."""
    return {**(old or {}), **(new or {})}


class RunMeta(TypedDict, total=False):
    run_id: str
    thread_id: str
    mode: str
    input_text: str
    files: list[dict[str, Any]]
    inputs: dict[str, Any]


def keep_first(old: Any, new: Any) -> Any:
    """run_meta is read-only for nodes: the run's initial value wins."""
    return old if old else new


class FlowState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    data: Annotated[dict[str, Any], merge_data]
    ports: Annotated[dict[str, Any], merge_keyed]  # "{node_id}.{output_name}" → value
    route: Annotated[dict[str, str], merge_keyed]  # node_id → chosen label
    run_meta: Annotated[RunMeta, keep_first]


def initial_state(
    *,
    run_id: str = "",
    thread_id: str = "",
    mode: str = "api",
    input_text: str = "",
    data: dict[str, Any] | None = None,
    files: list[dict[str, Any]] | None = None,
    messages: list[AnyMessage] | None = None,
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    msgs: list[AnyMessage] = list(messages or [])
    if input_text and not msgs:
        msgs = [HumanMessage(input_text)]
    state: dict[str, Any] = {
        "messages": msgs,
        "ports": {},
        "route": {},
        "run_meta": {
            "run_id": run_id,
            "thread_id": thread_id,
            "mode": mode,
            "input_text": input_text,
            "files": files or [],
        },
    }
    if data:
        state["data"] = data
    return state
