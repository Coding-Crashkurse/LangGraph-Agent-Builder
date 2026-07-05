"""FlowSpec -> compiled StateGraph: validation (all issues collected) then build.
See CLAUDE.md §7 for the rules; cycles are allowed, this is LangGraph."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from graphforge.compiler.spec import END_NODE, START_NODE, FlowSpec, ValidationIssue
from graphforge.components.base import (
    BaseComponent,
    BuildContext,
    ComponentConfig,
    NodeFn,
    RouterComponent,
    ToolProviderComponent,
)
from graphforge.components.registry import ComponentRegistry
from graphforge.runtime.events import current_node
from graphforge.runtime.state import FLOW_STATE_KEYS, FlowState
from graphforge.settings import Settings


class FlowValidationError(Exception):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(i.message for i in issues if i.severity == "error"))


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _parse_config(
    cls: type[BaseComponent], raw: dict[str, Any]
) -> tuple[ComponentConfig | None, list[str]]:
    try:
        return cls.config_model(**raw), []
    except ValidationError as exc:
        return None, [
            f"{'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
            for err in exc.errors()
        ]


def validate(spec: FlowSpec, registry: ComponentRegistry) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def error(code: str, message: str, **refs: Any) -> None:
        issues.append(ValidationIssue(severity="error", code=code, message=message, **refs))

    def warning(code: str, message: str, **refs: Any) -> None:
        issues.append(ValidationIssue(severity="warning", code=code, message=message, **refs))

    # 1. nodes: unique ids, known components, valid configs -----------------
    nodes_by_id: dict[str, Any] = {}
    configs: dict[str, ComponentConfig] = {}
    components: dict[str, BaseComponent] = {}
    for node in spec.nodes:
        if node.id in (START_NODE, END_NODE):
            error("reserved_node_id", f"'{node.id}' is reserved", node_id=node.id)
            continue
        if node.id in nodes_by_id:
            error("duplicate_node_id", f"duplicate node id '{node.id}'", node_id=node.id)
            continue
        nodes_by_id[node.id] = node
        cls = registry.get(node.component)
        if cls is None:
            error(
                "unknown_component",
                f"node '{node.id}': unknown component '{node.component}'",
                node_id=node.id,
            )
            continue
        if cls.version != node.component_version:
            error(
                "component_version_mismatch",
                f"node '{node.id}': component '{node.component}' is at version "
                f"{cls.version}, flow references {node.component_version}",
                node_id=node.id,
            )
        config, config_errors = _parse_config(cls, node.config)
        for msg in config_errors:
            error("invalid_config", f"node '{node.id}': {msg}", node_id=node.id)
        if config is not None:
            configs[node.id] = config
        components[node.id] = cls()

        # 5. state reads/writes must exist in FlowState ----------------------
        for key in [*cls.state_reads, *cls.state_writes]:
            if key not in FLOW_STATE_KEYS:
                error(
                    "unknown_state_key",
                    f"node '{node.id}': component declares unknown state key '{key}'",
                    node_id=node.id,
                )

    def is_provider(node_id: str) -> bool:
        comp = components.get(node_id)
        return isinstance(comp, ToolProviderComponent)

    def is_router(node_id: str) -> bool:
        comp = components.get(node_id)
        return isinstance(comp, RouterComponent)

    # 2. edges reference known nodes ----------------------------------------
    control_out: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    start_edges: list[int] = []
    seen_edges: set[tuple[str, str | None, str, str]] = set()
    for index, edge in enumerate(spec.edges):
        key = (edge.source, edge.source_handle, edge.target, edge.kind)
        if key in seen_edges:
            warning(
                "duplicate_edge", f"duplicate edge {edge.source} -> {edge.target}", edge_index=index
            )
        seen_edges.add(key)

        if edge.kind == "attach":
            if edge.source not in nodes_by_id:
                error(
                    "unknown_edge_node",
                    f"attach edge source '{edge.source}' does not exist",
                    edge_index=index,
                )
                continue
            if edge.target not in nodes_by_id:
                error(
                    "unknown_edge_node",
                    f"attach edge target '{edge.target}' does not exist",
                    edge_index=index,
                )
                continue
            # 4. attach: provider -> accepting node ---------------------------
            source_comp = components.get(edge.source)
            target_cls = registry.get(nodes_by_id[edge.target].component)
            if not isinstance(source_comp, ToolProviderComponent):
                error(
                    "attach_source_not_provider",
                    f"attach edge source '{edge.source}' is not a tool provider",
                    edge_index=index,
                )
            elif target_cls is not None and (
                source_comp.attachment_kind not in target_cls.accepts_attachments
            ):
                error(
                    "attach_not_accepted",
                    f"node '{edge.target}' does not accept "
                    f"'{source_comp.attachment_kind}' attachments",
                    edge_index=index,
                )
            continue

        # control edges -------------------------------------------------------
        if edge.source == END_NODE:
            error("edge_from_end", "control edge cannot start at __end__", edge_index=index)
            continue
        if edge.target == START_NODE:
            error("edge_into_start", "control edge cannot target __start__", edge_index=index)
            continue
        if edge.source != START_NODE and edge.source not in nodes_by_id:
            error(
                "unknown_edge_node", f"edge source '{edge.source}' does not exist", edge_index=index
            )
            continue
        if edge.target != END_NODE and edge.target not in nodes_by_id:
            error(
                "unknown_edge_node", f"edge target '{edge.target}' does not exist", edge_index=index
            )
            continue
        if edge.source == START_NODE:
            start_edges.append(index)
        for endpoint in (edge.source, edge.target):
            if endpoint in nodes_by_id and is_provider(endpoint):
                error(
                    "provider_in_control_flow",
                    f"tool provider '{endpoint}' cannot be part of control flow",
                    edge_index=index,
                )
        if edge.source in nodes_by_id:
            control_out[edge.source].append((index, edge))

    # 2. exactly one __start__ edge ------------------------------------------
    if len(start_edges) == 0:
        error("missing_start", "flow needs exactly one edge from __start__")
    elif len(start_edges) > 1:
        for index in start_edges[1:]:
            error(
                "multiple_start", "flow must have exactly one edge from __start__", edge_index=index
            )

    # 3. router wiring / single unlabeled out-edge ----------------------------
    for node_id in nodes_by_id:
        outgoing = control_out.get(node_id, [])
        if is_router(node_id):
            component = components[node_id]
            config = configs.get(node_id)
            if config is None:
                continue  # config errors already reported
            labels = list(component.outputs(config))  # type: ignore[attr-defined]
            wired: dict[str, int] = {}
            for index, edge in outgoing:
                if not edge.source_handle:
                    error(
                        "router_unlabeled_edge",
                        f"router '{node_id}': outgoing edges need a source_handle",
                        edge_index=index,
                        node_id=node_id,
                    )
                elif edge.source_handle not in labels:
                    error(
                        "unknown_router_output",
                        f"router '{node_id}': unknown output '{edge.source_handle}' "
                        f"(expected one of {labels})",
                        edge_index=index,
                        node_id=node_id,
                    )
                elif edge.source_handle in wired:
                    error(
                        "router_output_rewired",
                        f"router '{node_id}': output '{edge.source_handle}' wired twice",
                        edge_index=index,
                        node_id=node_id,
                    )
                else:
                    wired[edge.source_handle] = index
            for label in labels:
                if label not in wired:
                    error(
                        "router_output_unwired",
                        f"router '{node_id}': output '{label}' is not wired",
                        node_id=node_id,
                    )
        else:
            if len(outgoing) > 1:
                for index, _ in outgoing[1:]:
                    error(
                        "multiple_out_edges",
                        f"node '{node_id}': only one outgoing control edge allowed",
                        edge_index=index,
                        node_id=node_id,
                    )
            for index, edge in outgoing:
                if edge.source_handle:
                    error(
                        "dangling_handle",
                        f"node '{node_id}' is not a router; edge must not carry "
                        f"source_handle '{edge.source_handle}'",
                        edge_index=index,
                        node_id=node_id,
                    )

    # 2. reachability from __start__ over control edges ------------------------
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in spec.edges:
        if edge.kind == "control" and edge.target != END_NODE:
            adjacency[edge.source].add(edge.target)
    reachable: set[str] = set()
    frontier = [START_NODE]
    while frontier:
        current = frontier.pop()
        for nxt in adjacency.get(current, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    for node_id in nodes_by_id:
        if is_provider(node_id):
            if not any(e.kind == "attach" and e.source == node_id for e in spec.edges):
                warning(
                    "unused_provider",
                    f"tool provider '{node_id}' is not attached to any node",
                    node_id=node_id,
                )
            continue
        if node_id not in reachable:
            error(
                "unreachable_node",
                f"node '{node_id}' is not reachable from __start__",
                node_id=node_id,
            )

    return issues


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


class AttachmentResolver:
    """Resolves tools of attached providers lazily on first run, cached per flow."""

    def __init__(self) -> None:
        self._providers: dict[str, list[tuple[ToolProviderComponent, ComponentConfig]]] = (
            defaultdict(list)
        )
        self._cache: dict[str, list[Any]] = {}
        self._lock = asyncio.Lock()

    def attach(
        self, target_node: str, provider: ToolProviderComponent, config: ComponentConfig
    ) -> None:
        self._providers[target_node].append((provider, config))

    def has_attachments(self, node_id: str) -> bool:
        return bool(self._providers.get(node_id))

    async def get_tools(self, node_id: str) -> list[Any]:
        providers = self._providers.get(node_id, [])
        if not providers:
            return []
        if node_id in self._cache:
            return self._cache[node_id]
        async with self._lock:
            if node_id in self._cache:
                return self._cache[node_id]
            tools: list[Any] = []
            for provider, config in providers:
                tools.extend(await provider.get_tools(config))
            self._cache[node_id] = tools
            return tools


@dataclass
class CompiledFlow:
    spec: FlowSpec
    graph: Any  # CompiledStateGraph
    resolver: AttachmentResolver = field(default_factory=AttachmentResolver)


def _with_node_context(node_id: str, fn: NodeFn) -> NodeFn:
    """Set the current-node contextvar around the node call so emitted custom
    events carry their node id. The RunnableConfig annotation is load-bearing:
    langgraph passes the config positionally only when it is typed."""

    async def wrapped(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        token = current_node.set(node_id)
        try:
            return await fn(state, config)
        finally:
            current_node.reset(token)

    wrapped.__name__ = f"node_{node_id}"
    return wrapped


def _route_by_state(state: dict[str, Any]) -> str:
    route = state.get("route")
    if route is None:
        raise RuntimeError("router node finished without writing state['route']")
    return str(route)


def build_flow(
    spec: FlowSpec,
    registry: ComponentRegistry,
    settings: Settings,
    checkpointer: Any,
) -> CompiledFlow:
    """Validate then build. Raises FlowValidationError when errors exist."""
    issues = validate(spec, registry)
    if any(issue.severity == "error" for issue in issues):
        raise FlowValidationError([i for i in issues if i.severity == "error"])

    resolver = AttachmentResolver()
    components: dict[str, BaseComponent] = {}
    configs: dict[str, ComponentConfig] = {}
    for node in spec.nodes:
        cls = registry.get(node.component)
        assert cls is not None  # validated above
        components[node.id] = cls()
        configs[node.id] = cls.config_model(**node.config)

    # attach edges first so BuildContext.get_attached_tools sees them
    for edge in spec.edges:
        if edge.kind == "attach":
            provider = components[edge.source]
            assert isinstance(provider, ToolProviderComponent)
            resolver.attach(edge.target, provider, configs[edge.source])

    graph: StateGraph = StateGraph(FlowState)
    routers: list[str] = []
    for node in spec.nodes:
        component = components[node.id]
        if isinstance(component, ToolProviderComponent):
            continue
        ctx = BuildContext(
            settings=settings,
            flow_id=spec.id or spec.slug,
            flow_slug=spec.slug,
            node_id=node.id,
            attachments=resolver,
        )
        node_fn = component.build(configs[node.id], ctx)
        graph.add_node(node.id, _with_node_context(node.id, node_fn))
        if isinstance(component, RouterComponent):
            routers.append(node.id)

    def resolve_target(target: str) -> Any:
        return END if target == END_NODE else target

    router_targets: dict[str, dict[str, Any]] = defaultdict(dict)
    for edge in spec.edges:
        if edge.kind != "control":
            continue
        if edge.source == START_NODE:
            graph.add_edge(START, resolve_target(edge.target))
        elif edge.source in routers:
            assert edge.source_handle is not None  # validated
            router_targets[edge.source][edge.source_handle] = resolve_target(edge.target)
        else:
            graph.add_edge(edge.source, resolve_target(edge.target))

    for router_id, mapping in router_targets.items():
        graph.add_conditional_edges(router_id, _route_by_state, mapping)

    compiled = graph.compile(checkpointer=checkpointer)
    return CompiledFlow(spec=spec, graph=compiled, resolver=resolver)
