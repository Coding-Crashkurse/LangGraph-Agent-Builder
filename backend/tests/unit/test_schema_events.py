"""Unit tests for schema.events — RunEvent envelope + SSE shape (SPEC §6.2)."""

from __future__ import annotations

import json
from datetime import datetime

from langgraph_agent_builder.schema.events import RunEvent


def test_run_event_defaults() -> None:
    event = RunEvent(event="run_started", run_id="r1")
    assert event.thread_id == ""
    assert event.seq == 0
    assert event.data == {}
    # ts default factory produces a parseable ISO-8601 timestamp.
    assert isinstance(datetime.fromisoformat(event.ts), datetime)


def test_run_event_sse_payload_shape() -> None:
    event = RunEvent(
        event="node_token",
        run_id="r1",
        thread_id="t1",
        seq=7,
        data={"token": "hi"},
    )
    sse = event.sse()
    assert sse["event"] == "node_token"
    assert sse["id"] == "7"  # id is str(seq)
    decoded = json.loads(sse["data"])
    assert decoded["run_id"] == "r1"
    assert decoded["seq"] == 7
    assert decoded["data"] == {"token": "hi"}


def test_run_event_custom_type_and_data_roundtrip() -> None:
    event = RunEvent(event="custom.metric", run_id="r2", data={"n": 5})
    sse = event.sse()
    assert sse["event"] == "custom.metric"
    assert json.loads(sse["data"])["data"]["n"] == 5
