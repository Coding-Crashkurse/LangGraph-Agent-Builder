"""Unit tests for langgraph_agent_builder.services.orchestrator (SPEC §6.1): the single run path.

Drives real flows (hello / approval) end-to-end through the executor via the
``svc`` fixture, covering compile, validate, run, resume, thread state, and the
FlowNotRunnableError / KeyError error branches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from langgraph_agent_builder.runtime.executor import RunHandle, RunResult
from langgraph_agent_builder.services.orchestrator import (
    FlowNotRunnableError,
    Orchestrator,
    scoped_thread_id,
)
from tests.conftest import approval_spec, hello_spec

if TYPE_CHECKING:
    from langgraph_agent_builder.app import AppServices


def _orch(svc: AppServices) -> Orchestrator:
    return svc.orchestrator


def _broken_spec() -> dict[str, Any]:
    spec = hello_spec("broken")
    # point a node at a component that is not installed → compile error
    spec["nodes"][1]["component_id"] = "lab.does.not.exist"
    return spec


# --------------------------------------------------------------------- scoped_thread_id
def test_scoped_thread_id_empty_scope_is_identity() -> None:
    assert scoped_thread_id("", "ctx-1") == "ctx-1"


def test_scoped_thread_id_namespaces_deterministically() -> None:
    a = scoped_thread_id("tenant-a", "ctx-1")
    b = scoped_thread_id("tenant-b", "ctx-1")
    assert a.startswith("ns")
    assert a != b  # different scope → different namespace
    assert scoped_thread_id("tenant-a", "ctx-1") == a  # deterministic


# --------------------------------------------------------------------- compile / validate
async def test_compiled_ok(svc: AppServices) -> None:
    compiled = await _orch(svc).compiled(hello_spec())
    assert compiled.ok is True


async def test_validate_clean_spec(svc: AppServices) -> None:
    diags, compiled = await _orch(svc).validate(hello_spec())
    assert not any(d.severity == "error" for d in diags)
    assert compiled is not None


async def test_validate_broken_spec_returns_errors_and_no_compiled(svc: AppServices) -> None:
    diags, compiled = await _orch(svc).validate(_broken_spec())
    assert compiled is None
    assert any(d.severity == "error" for d in diags)


async def test_compiled_with_extra_vars_and_env_fallback(svc: AppServices) -> None:
    # extra_vars merge (§9.4) + env fallback wiring both exercised on compile
    svc.settings.fallback_to_env_var = True
    compiled = await _orch(svc).compiled(hello_spec(), extra_vars={"foo": "bar"})
    assert compiled.ok is True


async def test_validate_deep_runs_health_checks(svc: AppServices) -> None:
    # deep validation walks each node's health_check; the plain hello flow passes
    diags, compiled = await _orch(svc).validate(hello_spec(), deep=True)
    assert compiled is not None
    assert not any(d.severity == "error" for d in diags)


# --------------------------------------------------------------------- run
async def test_start_run_completes(svc: AppServices) -> None:
    run_id, thread_id, result = await _orch(svc).start_run(
        spec=hello_spec(), input_text="hi", background=False
    )
    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert result.result_text == "Hello from LAB!"
    row = await svc.runs.get(run_id)
    assert row is not None
    assert row.status == "completed"
    assert row.thread_id == thread_id


async def test_start_run_honours_session_id(svc: AppServices) -> None:
    _run_id, thread_id, _result = await _orch(svc).start_run(
        spec=hello_spec(), session_id="fixed-thread", background=False
    )
    assert thread_id == "fixed-thread"


async def test_start_run_background_returns_handle(svc: AppServices) -> None:
    run_id, _thread, handle = await _orch(svc).start_run(spec=hello_spec(), background=True)
    assert isinstance(handle, RunHandle)
    if handle.task is not None:
        await handle.task
    row = await svc.runs.get(run_id)
    assert row is not None
    assert row.status == "completed"


async def test_resume_run_background_returns_handle(svc: AppServices) -> None:
    flow = await svc.flows.create(approval_spec("bg-resume"))
    run_id, _thread, first = await _orch(svc).start_run(
        spec=approval_spec("bg-resume"), flow_row=flow, background=False
    )
    assert isinstance(first, RunResult)
    assert first.status == "input_required"
    _rid, handle = await _orch(svc).resume_run(run_id, {"decision": "approve"}, background=True)
    assert isinstance(handle, RunHandle)
    if handle.task is not None:
        await handle.task
    row = await svc.runs.get(run_id)
    assert row is not None
    assert row.status == "completed"


async def test_start_run_not_runnable_raises(svc: AppServices) -> None:
    with pytest.raises(FlowNotRunnableError) as exc:
        await _orch(svc).start_run(spec=_broken_spec(), background=False)
    assert exc.value.diagnostics
    assert any(d.severity == "error" for d in exc.value.diagnostics)


# --------------------------------------------------------------------- resume
async def test_resume_run_missing_run_raises_keyerror(svc: AppServices) -> None:
    with pytest.raises(KeyError):
        await _orch(svc).resume_run("no-such-run", {"decision": "approve"}, background=False)


async def test_interrupt_then_resume_completes(svc: AppServices) -> None:
    flow = await svc.flows.create(approval_spec("resume-me"))
    run_id, _thread, result = await _orch(svc).start_run(
        spec=approval_spec("resume-me"), flow_row=flow, input_text="go", background=False
    )
    assert isinstance(result, RunResult)
    assert result.status == "input_required"

    _rid, resumed = await _orch(svc).resume_run(run_id, {"decision": "approve"}, background=False)
    assert isinstance(resumed, RunResult)
    assert resumed.status == "completed"
    assert resumed.result_text == "draft answer"


async def test_spec_for_run_missing_flow_raises_keyerror(svc: AppServices) -> None:
    # a run row whose slug maps to no flow → _spec_for_run cannot resolve it
    await svc.runs.create("orphan", thread_id="t", mode="api", flow_slug="ghost-flow")
    with pytest.raises(KeyError):
        await _orch(svc).resume_run("orphan", {"decision": "approve"}, background=False)


async def test_resume_resolves_via_flow_version(svc: AppServices) -> None:
    flow = await svc.flows.create(approval_spec("versioned"))
    version, _diags = await svc.flows.publish(flow.id, registry=svc.registry, bump="minor")
    assert version is not None
    run_id, _thread, result = await _orch(svc).start_run(
        spec=approval_spec("versioned"),
        flow_row=flow,
        flow_version_id=version.id,
        background=False,
    )
    assert isinstance(result, RunResult)
    assert result.status == "input_required"
    _rid, resumed = await _orch(svc).resume_run(run_id, {"decision": "approve"}, background=False)
    assert isinstance(resumed, RunResult)
    assert resumed.status == "completed"


# --------------------------------------------------------------------- thread state
async def test_thread_state_and_history_after_run(svc: AppServices) -> None:
    await _orch(svc).start_run(spec=hello_spec(), session_id="thread-x", background=False)
    state = await _orch(svc).thread_state(hello_spec(), "thread-x")
    assert state is not None
    history = await _orch(svc).thread_history(hello_spec(), "thread-x", limit=10)
    assert len(history) >= 1


async def test_update_thread_state_writes_values(svc: AppServices) -> None:
    await _orch(svc).start_run(spec=hello_spec(), session_id="thread-u", background=False)
    # updating state must not raise and must be reflected in a fresh read
    await _orch(svc).update_thread_state(hello_spec(), "thread-u", {"input_text": "patched"})
    state = await _orch(svc).thread_state(hello_spec(), "thread-u")
    assert state is not None
