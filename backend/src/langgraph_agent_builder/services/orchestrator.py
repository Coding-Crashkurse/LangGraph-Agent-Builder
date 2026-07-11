"""Orchestrator: compile-with-DB-variables + run/resume/cancel glue.

The one place where flows, secrets, executor, and run bookkeeping meet — all
run modes (playground/api/debug/a2a/mcp/webhook) go through here (SPEC §6.1).
"""

from __future__ import annotations

import hashlib
from typing import Any

from ulid import ULID

from langgraph_agent_builder.compiler import CompiledFlow, compile_flow
from langgraph_agent_builder.db.models import FlowRow
from langgraph_agent_builder.errors import LabRuntimeError
from langgraph_agent_builder.runtime.executor import Executor, RunHandle, RunResult
from langgraph_agent_builder.schema.diagnostics import Diagnostic
from langgraph_agent_builder.schema.flowspec import FlowSpec, parse_flowspec
from langgraph_agent_builder.sdk.component import SecretsResolver
from langgraph_agent_builder.sdk.registry import ComponentRegistry
from langgraph_agent_builder.services.runs import RunService
from langgraph_agent_builder.services.secrets import SecretsService, SnapshotVariablesProvider
from langgraph_agent_builder.services.settings import Settings


def scoped_thread_id(scope: str, context_id: str) -> str:
    """Public-agent session namespacing (SPEC §7.11)."""
    if not scope:
        return context_id
    digest = hashlib.sha256(f"{scope}|{context_id}".encode()).hexdigest()[:32]
    return f"ns{digest}"


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ComponentRegistry,
        secrets: SecretsService,
        runs: RunService,
        executor: Executor,
        vectorstores: Any = None,
        resources: Any = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.secrets = secrets
        self.runs = runs
        self.executor = executor
        self.vectorstores = vectorstores
        self.resources = resources

    # ---------------------------------------------------------------- compile
    async def _vectorstore_names(self) -> set[str] | None:
        if self.vectorstores is None:
            return None
        return {c["name"] for c in await self.vectorstores.list()}

    async def _resources(self) -> dict[str, str] | None:
        if self.resources is None:
            return None
        names: dict[str, str] = await self.resources.names_with_types()
        return names

    async def compiled(
        self,
        spec: dict[str, Any] | FlowSpec,
        *,
        tweaks: dict[str, dict[str, Any]] | None = None,
        extra_vars: dict[str, str] | None = None,
    ) -> CompiledFlow:
        variables, secret_values = await self.secrets.snapshot()
        if extra_vars:
            # header-passed globals override generic vars for this run only (§9.4)
            variables = {**variables, **extra_vars}
        vs_provider = SnapshotVariablesProvider(variables, secret_values)
        if self.settings.fallback_to_env_var:
            import os

            # NOTE(SPEC §9.4/§10.3): the spec says run-start env-fallback misses
            # "still raise RT106", but every $var/$secret miss (env fallback
            # included) surfaces right here at compile time as E012 — before a
            # run row exists to store an RT code on. RT106 is therefore
            # unreachable in this implementation; SPEC amendment pending.
            vs_provider.env_fallback = lambda name: os.environ.get(name)  # type: ignore[attr-defined]
        return compile_flow(
            parse_flowspec(spec),
            registry=self.registry,
            variables=vs_provider,
            secrets=SecretsResolver(secret_values),
            tweaks=tweaks,
            settings=self.settings,
            vectorstore_names=await self._vectorstore_names(),
            resources=await self._resources(),
            use_cache=not tweaks,
        )

    async def validate(
        self, spec: dict[str, Any] | FlowSpec, deep: bool = False
    ) -> tuple[list[Diagnostic], CompiledFlow | None]:
        compiled = await self.compiled(spec)
        diags = list(compiled.diagnostics)
        if deep and compiled.ok:
            diags += await self._deep_checks(compiled)
        return diags, (compiled if compiled.ok else None)

    async def _deep_checks(self, compiled: CompiledFlow) -> list[Diagnostic]:
        from langgraph_agent_builder.schema.diagnostics import DiagnosticCode
        from langgraph_agent_builder.vectorstores.base import (
            BackendExtraMissing,
            CollectionMissing,
            DimensionMismatch,
            VectorStoreError,
        )

        diags: list[Diagnostic] = []
        assert compiled.ir is not None
        for node in compiled.ir.nodes.values():
            ctx = compiled.node_contexts.get(node.id) or node.build_ctx
            if ctx is None:
                continue
            try:
                await node.component().health_check(ctx)
            except BackendExtraMissing as exc:
                diags.append(
                    Diagnostic.make(
                        DiagnosticCode.E901, str(exc), node_id=node.id, fix_hint=exc.detail
                    )
                )
            except CollectionMissing as exc:
                diags.append(Diagnostic.make(DiagnosticCode.E903, str(exc), node_id=node.id))
            except DimensionMismatch as exc:
                diags.append(Diagnostic.make(DiagnosticCode.E904, str(exc), node_id=node.id))
            except VectorStoreError as exc:
                diags.append(Diagnostic.make(DiagnosticCode.E902, str(exc), node_id=node.id))
            except Exception as exc:
                diags.append(
                    Diagnostic.make(
                        DiagnosticCode.E902,
                        f"health check failed for {node.id!r}: {exc}",
                        node_id=node.id,
                    )
                )
        return diags

    # ---------------------------------------------------------------- run
    async def start_run(
        self,
        *,
        spec: dict[str, Any] | FlowSpec,
        flow_row: FlowRow | None = None,
        flow_version_id: str | None = None,
        mode: str = "api",
        input_text: str = "",
        data: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        tweaks: dict[str, dict[str, Any]] | None = None,
        debug: bool = False,
        background: bool = True,
        until_node: str | None = None,
        extra_vars: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> tuple[str, str, RunHandle | RunResult]:
        """Create the run row and start execution; returns (run_id, thread_id, handle|result)."""
        compiled = await self.compiled(spec, tweaks=tweaks, extra_vars=extra_vars)
        if not compiled.ok:
            errors = "; ".join(
                f"{d.code}: {d.message}" for d in compiled.diagnostics if d.severity == "error"
            )
            raise FlowNotRunnableError(errors, compiled.diagnostics)
        run_id = run_id or str(ULID()).lower()
        thread_id = session_id or str(ULID()).lower()
        await self.runs.create(
            run_id,
            thread_id=thread_id,
            mode=mode,
            flow_id=flow_row.id if flow_row else None,
            flow_version_id=flow_version_id,
            flow_slug=compiled.spec.flow.slug,
        )
        kwargs: dict[str, Any] = dict(
            run_id=run_id,
            thread_id=thread_id,
            mode=mode,
            input_text=input_text,
            data=data,
            files=files,
            debug=debug,
            until_node=until_node,
        )
        if background:
            handle = self.executor.start(compiled, **kwargs)
            return run_id, thread_id, handle
        result = await self.executor.execute(compiled, **kwargs)
        return run_id, thread_id, result

    async def resume_run(
        self,
        run_id: str,
        payload: Any,
        *,
        debug_action: str | None = None,
        background: bool = True,
    ) -> tuple[str, RunHandle | RunResult]:
        run = await self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        spec, _flow_row = await self._spec_for_run(run)
        compiled = await self.compiled(spec)
        bus = self.executor.bus
        if bus is not None:
            # after a restart the bus's in-memory seq counters are gone; resume
            # numbering above the persisted events, or every new event collides
            # with uq_run_event_seq and live SSE tails filter them out (§6.2)
            bus.set_seq_floor(run_id, await self.runs.max_seq(run_id))
        kwargs: dict[str, Any] = dict(
            run_id=run_id,
            thread_id=run.thread_id,
            mode=run.mode,
            resume=None if debug_action else payload,
            debug_action=debug_action,
        )
        if background:
            return run_id, self.executor.start(compiled, **kwargs)
        return run_id, await self.executor.execute(compiled, **kwargs)

    async def _spec_for_run(self, run: Any) -> tuple[dict[str, Any], FlowRow | None]:
        from sqlalchemy import select

        from langgraph_agent_builder.db.models import FlowVersionRow

        async with self.runs.session() as session:  # same sessionmaker as run rows
            if run.flow_version_id:
                version = await session.get(FlowVersionRow, run.flow_version_id)
                if version is not None:
                    flow = await session.get(FlowRow, run.flow_id) if run.flow_id else None
                    return version.flowspec, flow
            if run.flow_id:
                flow = await session.get(FlowRow, run.flow_id)
                if flow is not None:
                    return flow.spec, flow
            row = (
                await session.execute(select(FlowRow).where(FlowRow.slug == run.flow_slug))
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"flow for run {run.id} not found")
            return row.spec, row

    # ---------------------------------------------------------------- threads
    async def thread_state(self, spec: dict[str, Any] | FlowSpec, thread_id: str) -> Any:
        compiled = await self.compiled(spec)
        checkpointer = await self.executor.get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        return await graph.aget_state({"configurable": {"thread_id": thread_id}})

    async def thread_history(
        self, spec: dict[str, Any] | FlowSpec, thread_id: str, limit: int = 50
    ) -> list[Any]:
        compiled = await self.compiled(spec)
        checkpointer = await self.executor.get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        history = []
        async for snapshot in graph.aget_state_history({"configurable": {"thread_id": thread_id}}):
            history.append(snapshot)
            if len(history) >= limit:
                break
        return history

    async def update_thread_state(
        self, spec: dict[str, Any] | FlowSpec, thread_id: str, values: dict[str, Any]
    ) -> None:
        compiled = await self.compiled(spec)
        checkpointer = await self.executor.get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        await graph.aupdate_state({"configurable": {"thread_id": thread_id}}, values)


class FlowNotRunnableError(LabRuntimeError):
    def __init__(self, message: str, diagnostics: list[Diagnostic]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
