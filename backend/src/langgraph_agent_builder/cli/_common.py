"""CLI plumbing: env-file precedence, settings assembly, exit codes (SPEC §2.6)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from lga.services.settings import Settings

console = Console()
err_console = Console(stderr=True)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_CONNECTION = 4


def ensure_selector_policy() -> None:
    """psycopg async cannot run on the Windows Proactor loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def load_env_files(env_file: Path | None) -> None:
    """Precedence: process env > --env-file > ./.env (override=False keeps it)."""
    from dotenv import load_dotenv

    if env_file is not None:
        if not env_file.exists():
            err_console.print(f"[red]env file not found:[/red] {env_file}")
            raise SystemExit(EXIT_USAGE)
        load_dotenv(env_file, override=False)
    load_dotenv(Path(".env"), override=False)


def build_settings(env_file: Path | None = None, **flag_overrides: Any) -> Settings:
    """CLI flag > env > --env-file > ./.env > defaults."""
    from lga.services.settings import Settings

    load_env_files(env_file)
    overrides = {k: v for k, v in flag_overrides.items() if v is not None}
    return Settings(**overrides)


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    ensure_selector_policy()
    return asyncio.run(coro)
