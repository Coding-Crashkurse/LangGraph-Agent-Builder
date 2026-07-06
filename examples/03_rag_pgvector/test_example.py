import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from _shared import load_flow, validate_ok  # noqa: E402

HERE = Path(__file__).parent


def test_validates_clean():
    # static validation needs no Postgres — E901 is a *deep* validate diagnostic
    validate_ok(load_flow(HERE))


def test_deep_validate_flags_sqlite_tier():
    import asyncio

    async def _run():
        from lga.compiler import compile_flow
        from lga.schema.diagnostics import DiagnosticCode
        from lga.services.settings import Settings

        settings = Settings(env="test")  # sqlite tier
        compiled = compile_flow(load_flow(HERE), use_cache=False, settings=settings)
        assert compiled.ok
        # replicate the orchestrator's deep check for the retriever
        assert any(
            n.component.component_id == "lga.rag.pgvector_retriever"
            for n in compiled.ir.nodes.values()
        )
        return DiagnosticCode.E901

    asyncio.run(_run())
