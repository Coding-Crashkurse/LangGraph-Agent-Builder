"""Component base classes (CLAUDE.md §6.1)."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from graphforge.settings import Settings

# Async node function: (state, config) -> partial state update.
NodeFn = Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]

Category = Literal["llm", "rag", "flow", "tools", "io"]


class ComponentConfig(BaseModel):
    """Base for all component configs. The JSON Schema of this model drives the UI form."""

    model_config = ConfigDict(extra="forbid")


class SupportsAttachments(Protocol):
    async def get_tools(self, node_id: str) -> list[Any]: ...


class BuildContext:
    """Passed to `Component.build`. Gives node functions access to settings and
    to the tools of attached tool providers (resolved lazily, cached per flow)."""

    def __init__(
        self,
        *,
        settings: "Settings",
        flow_id: str,
        flow_slug: str,
        node_id: str,
        attachments: SupportsAttachments,
    ) -> None:
        self.settings = settings
        self.flow_id = flow_id
        self.flow_slug = flow_slug
        self.node_id = node_id
        self._attachments = attachments

    async def get_attached_tools(self) -> list[Any]:
        """Tools from all providers attached to this node (empty list if none)."""
        return await self._attachments.get_tools(self.node_id)


class BaseComponent(ABC):
    # --- static metadata (class-level) ---
    name: ClassVar[str]  # unique snake_case id, e.g. "pgvector_retriever"
    display_name: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str]  # palette grouping: "llm" | "rag" | "flow" | "tools" | "io"
    version: ClassVar[int] = 1
    config_model: ClassVar[type[ComponentConfig]]
    state_reads: ClassVar[list[str]] = []
    state_writes: ClassVar[list[str]] = []
    accepts_attachments: ClassVar[list[str]] = []  # e.g. ["tools"] on agent components

    @abstractmethod
    def build(self, config: ComponentConfig, ctx: BuildContext) -> NodeFn:
        """Return an async node function: (state, config) -> partial state update.

        Node functions may call `graphforge.runtime.events.emit(type, data)` to
        stream custom progress events; it is a safe no-op when not streaming.
        """


class RouterComponent(BaseComponent):
    """Node with multiple labeled outputs, wired via `add_conditional_edges`.

    The node function must write one of `outputs(config)` into `state["route"]`.
    `outputs_static` / `outputs_from_config` describe the labels to the frontend
    (registry payload) so the canvas can render source handles without executing
    Python.
    """

    outputs_static: ClassVar[list[str] | None] = None
    outputs_from_config: ClassVar[str | None] = None  # config field holding list[str] labels

    @abstractmethod
    def outputs(self, config: ComponentConfig) -> list[str]:
        """Labels of the outgoing conditional branches."""


class ToolProviderComponent(BaseComponent):
    """Provides tools to agent nodes via `attach` edges; never a control-flow node."""

    attachment_kind: ClassVar[str] = "tools"

    @abstractmethod
    async def get_tools(self, config: ComponentConfig) -> list[Any]:  # list[BaseTool]
        ...

    def build(self, config: ComponentConfig, ctx: BuildContext) -> NodeFn:
        raise NotImplementedError("tool providers are not control-flow nodes")
