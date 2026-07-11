# 10 · headless_python

`pip install langgraph-agent-builder` and use it as a library — no frontend, no server, no keys
(SPEC §2.7): `compile_flow` → vanilla `StateGraph`, `arun_flow` for the runtime
path, and export-to-python (§5.7).

```bash
python examples/10_headless_python/main.py
# diagnostics: []
# vanilla result: Headless says hello.
# runtime result: completed → Headless says hello.
# exported → exported_flow.py (…)
python examples/10_headless_python/exported_flow.py   # runs under vanilla LangGraph
```

Same thing via the CLI: `lga flow run examples/10_headless_python/flow.json --local`.
