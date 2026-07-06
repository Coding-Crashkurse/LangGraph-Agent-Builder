"""Orchestrator: compile-with-DB-variables + run/resume/cancel glue.

The one place where flows, secrets, executor, and run bookkeeping meet — all
run modes (playground/api/debug/a2a/mcp/webhook) go through here (SPEC §6.1).
"""

from __future__ import annotations

import hashlib
from typing import Any

from ulid import ULID

from lga.compiler import CompiledFlow, compile_flow
from lga.db.models import FlowRow
from lga.runtime.executor import Executor, RunHandle, RunResult
from lga.schema.diagnostics import Diagnostic
from lga.schema.flowspec import FlowSpec, parse_flowspec
from lga.sdk.component import SecretsResolver
from lga.sdk.registry import ComponentRegistry
from lga.services.runs import RunService
from lga.services.secrets import SecretsService, SnapshotVariablesProvider
from lga.services.settings import Settings


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
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.secrets = secrets
        self.runs = runs
        self.executor = executor

    # ---------------------------------------------------------------- compile
    async def compiled(
        self,
        spec: dict[str, Any] | FlowSpec,
        *,
        tweaks: dict[str, dict[str, Any]] | None = None,
    ) -> CompiledFlow:
        variables, secret_values = await self.secrets.snapshot()
        return compile_flow(
            parse_flowspec(spec),
            registry=self.registry,
            variables=SnapshotVariablesProvider(variables, secret_values),
            secrets=SecretsResolver(secret_values),
            tweaks=tweaks,
            settings=self.settings,
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
        from lga.schema.diagnostics import DiagnosticCode

        diags: list[Diagnostic] = []
        assert compiled.ir is not None
        for node in compiled.ir.nodes.values():
            if node.component.component_id == "lga.rag.pgvector_retriever" and (
                not self.settings.is_postgres
            ):
                diags.append(
                    Diagnostic.make(
                        DiagnosticCode.E901,
                        f"node {node.id!r} requires Postgres (pgvector); current tier is "
                        f"{self.settings.storage_tier}",
                        node_id=node.id,
                        fix_hint="Set LGA_DATABASE_URL=postgresql+asyncpg://…",
                    )
                )
                continue
            ctx = compiled.node_contexts.get(node.id) or node.build_ctx
            if ctx is None:
                continue
            try:
                await node.component().health_check(ctx)
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
        run_id: str | None = None,
    ) -> tuple[str, str, RunHandle | RunResult]:
        """Create the run row and start execution; returns (run_id, thread_id, handle|result)."""
        compiled = await self.compiled(spec, tweaks=tweaks)
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

        from lga.db.models import FlowVersionRow

        sessions = self.runs._sessions  # same sessionmaker; internal wiring
        async with sessions() as session:
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
        checkpointer = await self.executor._get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        return await graph.aget_state({"configurable": {"thread_id": thread_id}})

    async def thread_history(
        self, spec: dict[str, Any] | FlowSpec, thread_id: str, limit: int = 50
    ) -> list[Any]:
        compiled = await self.compiled(spec)
        checkpointer = await self.executor._get_checkpointer()
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
        checkpointer = await self.executor._get_checkpointer()
        graph = compiled.compile(checkpointer=checkpointer)
        await graph.aupdate_state({"configurable": {"thread_id": thread_id}}, values)


class FlowNotRunnableError(RuntimeError):
    def __init__(self, message: str, diagnostics: list[Diagnostic]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
