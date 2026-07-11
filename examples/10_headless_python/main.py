"""Headless: compile + run a FlowSpec with zero frontend, zero server (SPEC §2.7).

    python examples/10_headless_python/main.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

FLOW = json.loads((Path(__file__).parent / "flow.json").read_text(encoding="utf-8"))


async def main() -> None:
    from langgraph_agent_builder.compiler import compile_flow
    from langgraph_agent_builder.runtime import arun_flow

    compiled = compile_flow(FLOW)
    print("diagnostics:", [f"{d.code.value}: {d.message}" for d in compiled.diagnostics])
    print("nodes:", [n["id"] for n in compiled.report.nodes])

    # 1) the compiled graph is vanilla LangGraph — usable without any lab runtime
    from langchain_core.messages import HumanMessage

    state = await compiled.graph.ainvoke(
        {"messages": [HumanMessage("hi")], "ports": {}, "route": {},
         "run_meta": {"input_text": "hi", "run_id": "demo", "thread_id": "demo"}}
    )
    print("vanilla result:", state["ports"]["end.result"].content)

    # 2) or with the lab runtime (events, interrupts, RT codes)
    result = await arun_flow(FLOW, input_text="hi again")
    print("runtime result:", result.status, "->", result.result_text)

    # 3) export to a standalone python file (SPEC §5.7)
    from langgraph_agent_builder.compiler.export_python import export_python
    from langgraph_agent_builder.schema.flowspec import parse_flowspec
    from langgraph_agent_builder.sdk.registry import get_registry

    exported = export_python(parse_flowspec(FLOW), get_registry())
    out = Path(__file__).parent / "exported_flow.py"
    out.write_text(exported, encoding="utf-8")
    print(f"exported -> {out.name} ({len(exported.splitlines())} lines)")


if __name__ == "__main__":
    asyncio.run(main())
