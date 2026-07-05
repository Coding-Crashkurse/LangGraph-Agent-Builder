"""Build the A2A Starlette (JSON-RPC) and FastAPI (REST) apps for a flow.

JSON-RPC is primary and always on; REST is enabled because the installed SDK
makes it cheap (A2ARESTFastAPIApplication); gRPC stays a feature-flagged
stretch (CLAUDE.md §5.8/§9.1)."""

import logging
from typing import Any

from a2a.server.apps import A2ARESTFastAPIApplication, A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskStore
from a2a.types import AgentCard

from graphforge.a2a.executor import LangGraphAgentExecutor

logger = logging.getLogger(__name__)

AGENT_CARD_PATH = "/.well-known/agent-card.json"


def build_a2a_apps(
    card: AgentCard,
    executor: LangGraphAgentExecutor,
    task_store: TaskStore,
) -> tuple[Any, Any | None]:
    """Returns (jsonrpc_asgi_app, rest_asgi_app | None) sharing one handler."""
    handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store)
    jsonrpc_app = A2AStarletteApplication(agent_card=card, http_handler=handler).build(
        agent_card_url=AGENT_CARD_PATH, rpc_url="/"
    )
    rest_app: Any | None = None
    try:
        rest_app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build(
            agent_card_url=AGENT_CARD_PATH
        )
    except Exception:  # keep JSON-RPC alive even if the REST variant regresses
        logger.exception("REST transport unavailable; serving JSON-RPC only")
    return jsonrpc_app, rest_app
