"""CLI: `graphforge serve` and `graphforge ingest <collection> <path>`.

On Windows the selector event-loop policy is set before uvicorn starts —
psycopg's async support does not work on the Proactor loop. (Trade-off:
stdio MCP toolsets need subprocess support and are therefore unavailable on
Windows; use streamable_http toolsets there.)"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _ensure_selector_policy() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    _ensure_selector_policy()
    if args.reload:
        # reload spawns a subprocess; uvicorn picks a selector loop there itself
        uvicorn.run(
            "graphforge.api.app:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level="info",
        )
        return
    # Run the server on a loop from OUR policy. uvicorn's loop factory would
    # force the Proactor loop on Windows, which psycopg async cannot use.
    config = uvicorn.Config(
        "graphforge.api.app:app", host=args.host, port=args.port, log_level="info"
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


def _ingest(args: argparse.Namespace) -> None:
    from graphforge.rag.ingest import ingest_path
    from graphforge.settings import get_settings

    _ensure_selector_policy()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"path not found: {path}")
    results = asyncio.run(ingest_path(get_settings(), args.collection, path))
    print(json.dumps(results, indent=2))
    print(f"ingested {sum(results.values())} chunks into '{args.collection}'")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="graphforge")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the backend (FastAPI + published flows)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_serve)

    ingest = sub.add_parser("ingest", help="ingest txt/md files into a pgvector collection")
    ingest.add_argument("collection")
    ingest.add_argument("path")
    ingest.set_defaults(func=_ingest)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
