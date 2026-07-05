"""FlowRuntimeManager: compile + mount/unmount published flows (CLAUDE.md §12).

Publishing mounts A2A (JSON-RPC + REST) and/or MCP ASGI sub-apps into the
running FastAPI app under /serve/… — no codegen, no subprocesses. MCP session
managers are entered per flow and closed on unmount.
"""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from a2a.server.tasks import TaskStore
from a2a.types import AgentCard
from fastapi import FastAPI
from starlette.routing import BaseRoute, Mount

from graphforge.a2a.card import a2a_url, build_agent_card, mcp_url, rest_url
from graphforge.a2a.executor import LangGraphAgentExecutor, RunRegistry
from graphforge.a2a.server import build_a2a_apps
from graphforge.compiler.build import CompiledFlow, build_flow
from graphforge.compiler.spec import FlowSpec
from graphforge.components.registry import ComponentRegistry
from graphforge.mcp_server.server import build_mcp_server
from graphforge.runtime.events import EventBus
from graphforge.runtime.runs import RunLog
from graphforge.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class MountedFlow:
    flow_id: str
    slug: str
    compiled: CompiledFlow
    routes: list[BaseRoute] = field(default_factory=list)
    mcp_stack: AsyncExitStack | None = None
    card: AgentCard | None = None
    rest_enabled: bool = False


class FlowRuntimeManager:
    def __init__(
        self,
        app: FastAPI,
        *,
        settings: Settings,
        registry: ComponentRegistry,
        bus: EventBus,
        task_store: TaskStore,
        checkpointer: Any,
        run_log: RunLog,
    ) -> None:
        self.app = app
        self.settings = settings
        self.registry = registry
        self.bus = bus
        self.task_store = task_store
        self.checkpointer = checkpointer
        self.run_log = run_log
        self.runs = RunRegistry()
        self._mounted: dict[str, MountedFlow] = {}

    # -- queries ---------------------------------------------------------------

    def is_mounted(self, flow_id: str) -> bool:
        return flow_id in self._mounted

    def mounted(self, flow_id: str) -> MountedFlow | None:
        return self._mounted.get(flow_id)

    def endpoints(self, flow_id: str) -> dict[str, str]:
        mf = self._mounted.get(flow_id)
        if mf is None:
            return {}
        endpoints: dict[str, str] = {}
        if mf.card is not None:
            base = a2a_url(self.settings, mf.slug)
            endpoints["a2a_url"] = base + "/"  # mount root; slash avoids a 307
            endpoints["agent_card_url"] = f"{base}/.well-known/agent-card.json"
            if mf.rest_enabled:
                endpoints["rest_url"] = rest_url(self.settings, mf.slug)
        if mf.mcp_stack is not None:
            endpoints["mcp_url"] = mcp_url(self.settings, mf.slug) + "/"
        return endpoints

    # -- mount / unmount ---------------------------------------------------------

    async def publish_flow(self, spec: FlowSpec) -> MountedFlow:
        """Validate, compile and mount. Raises FlowValidationError on errors.
        Republish = unmount first (idempotent)."""
        flow_id = spec.id or spec.slug
        await self.unpublish_flow(flow_id)

        compiled = build_flow(spec, self.registry, self.settings, self.checkpointer)
        mf = MountedFlow(flow_id=flow_id, slug=spec.slug, compiled=compiled)

        try:
            if spec.publish.a2a:
                executor = LangGraphAgentExecutor(
                    compiled.graph,
                    flow_id=flow_id,
                    flow_slug=spec.slug,
                    bus=self.bus,
                    run_log=self.run_log,
                    runs=self.runs,
                )
                jsonrpc_app, rest_app = build_a2a_apps(
                    build_agent_card(spec, self.settings, include_rest=rest_probe()),
                    executor,
                    self.task_store,
                )
                mf.rest_enabled = rest_app is not None
                mf.card = build_agent_card(spec, self.settings, include_rest=mf.rest_enabled)
                mf.routes.append(Mount(f"/serve/a2a/{spec.slug}", app=jsonrpc_app))
                if rest_app is not None:
                    mf.routes.append(Mount(f"/serve/rest/{spec.slug}", app=rest_app))

            if spec.publish.mcp:
                mcp_server = build_mcp_server(
                    spec,
                    compiled.graph,
                    settings=self.settings,
                    bus=self.bus,
                    run_log=self.run_log,
                    runs=self.runs,
                )
                http_app = mcp_server.streamable_http_app()
                stack = AsyncExitStack()
                await stack.enter_async_context(mcp_server.session_manager.run())
                mf.mcp_stack = stack
                mf.routes.append(Mount(f"/serve/mcp/{spec.slug}", app=http_app))
        except BaseException:
            if mf.mcp_stack is not None:
                await mf.mcp_stack.aclose()
            raise

        for route in mf.routes:
            self.app.router.routes.append(route)
        self._mounted[flow_id] = mf
        logger.info(
            "published flow '%s' (%s)", spec.slug, ", ".join(sorted(self.endpoints(flow_id)))
        )
        return mf

    async def unpublish_flow(self, flow_id: str) -> None:
        mf = self._mounted.pop(flow_id, None)
        if mf is None:
            return
        for route in mf.routes:
            try:
                self.app.router.routes.remove(route)
            except ValueError:
                pass
        if mf.mcp_stack is not None:
            try:
                await mf.mcp_stack.aclose()
            except Exception:
                logger.exception("error closing MCP session manager for '%s'", mf.slug)
        logger.info("unpublished flow '%s'", mf.slug)

    def cancel_run(self, run_id: str) -> bool:
        return self.runs.cancel(run_id)

    async def shutdown(self) -> None:
        for flow_id in list(self._mounted):
            await self.unpublish_flow(flow_id)


def rest_probe() -> bool:
    """REST transport is advertised iff the SDK class imports cleanly."""
    try:
        from a2a.server.apps import A2ARESTFastAPIApplication  # noqa: F401
    except Exception:
        return False
    return True
