"""`lab init` — scaffold a workspace (SPEC §2.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from langgraph_agent_builder.cli._common import EXIT_USAGE, console, err_console

ENV_TEMPLATE = """\
# lab configuration (SPEC §14). Every var has a CLI-flag twin.
# LAB_ENV=dev                     # dev enables hot-reload + http A2A
# LAB_HOST=127.0.0.1
# LAB_PORT=8000
# LAB_HOME=~/.langgraph-agent-builder                 # SQLite db, files, logs default root
# LAB_DATABASE_URL=sqlite+aiosqlite:///~/.langgraph-agent-builder/langgraph_agent_builder.db
#                                 # postgres: postgresql+asyncpg://user:pass@host:5432/lab
# LAB_SECRET_KEY=                 # Fernet key; REQUIRED in prod
# LAB_HOST_URL=                   # public base URL for agent cards / file links
# LAB_COMPONENTS_PATH=./components
# LAB_LOG_LEVEL=info
# LAB_AUTH_ENABLED=false
# LAB_A2A_TASK_STORE=db          # db | memory | my_pkg.module:factory (pluggable task manager)
# LAB_A2A_BLOCKING_TIMEOUT_S=30
# LAB_A2A_ACCEPTED_MIME=text/plain,application/json,application/pdf,image/*
# LAB_PUSH_ALLOW_PRIVATE=false    # SSRF guard for push webhooks
# LAB_MCP_TIMEOUT_S=120
# LAB_WEBHOOK_AUTH=true
# LAB_CHECKPOINT_TTL_DAYS=30
# LAB_FILES_DIR=./data/files
# Langflow-parity extras (SPEC §18.1):
# LAB_LOAD_FLOWS_PATH=./flows     # FlowSpec *.json imported at boot
# LAB_LOAD_FLOWS_OVERWRITE=false
# LAB_LOAD_FLOWS_PUBLISH=false    # auto-publish imports (A2A/MCP serve immediately)
# LAB_CREATE_STARTER_FLOWS=true
# LAB_AUTO_SAVING=true
# LAB_AUTO_SAVING_INTERVAL_MS=1000
# LAB_MAX_FILE_SIZE_MB=50
# LAB_MAX_TEXT_LENGTH=300
# LAB_SSL_CERT_FILE=              # TLS for lab run
# LAB_SSL_KEY_FILE=
# LAB_LOG_FILE=./lab.log
# Global variables / credentials:
# LAB_VAR_MY_SETTING=value
# LAB_CRED_OPENAI_API_KEY=sk-...
"""

EXAMPLE_COMPONENT = '''\
"""Example custom component — drop-in via LAB_COMPONENTS_PATH."""

from typing import Any

from langgraph_agent_builder.sdk import Component, Output, fields, ports


class Shout(Component):
    component_id = "workspace.data.shout"
    display_name = "Shout"
    description = "Uppercases its text input. Delete me."
    icon = "megaphone"
    category = "data"

    inputs = [
        fields.HandleField(name="input", display_name="Input", as_port=ports.TEXT),
        fields.IntInput(name="exclamation_marks", display_name="!", default=1, min=0, max=10),
    ]
    outputs = [Output(name="text", display_name="Text", port=ports.TEXT)]

    def build(self, ctx):
        async def node(state: dict[str, Any], config: Any) -> dict[str, Any]:
            text = str(ctx.get_input(state, "input") or "")
            marks = "!" * int(ctx.get_field("exclamation_marks") or 0)
            return {"text": text.upper() + marks}

        return node
'''

GITIGNORE = """\
.env
data/
__pycache__/
*.py[cod]
"""


def init_command(
    directory: Annotated[Path, typer.Argument(help="Workspace directory")] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files")] = False,
) -> None:
    """Scaffold a workspace: .env template, components/, flows/, .gitignore."""
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        directory / ".env": ENV_TEMPLATE,
        directory / "components" / "data" / "shout.py": EXAMPLE_COMPONENT,
        directory / "components" / "data" / "__init__.py": "",
        directory / "components" / "__init__.py": "",
        directory / ".gitignore": GITIGNORE,
    }
    (directory / "flows").mkdir(parents=True, exist_ok=True)
    for path in files:
        if path.exists() and not force:
            err_console.print(f"[red]{path} exists[/red] (use --force to overwrite)")
            raise typer.Exit(EXIT_USAGE)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    console.print(f"[green]workspace initialized in {directory.resolve()}[/green]")
    console.print("next: [bold]lab run --components-path ./components[/bold]")
