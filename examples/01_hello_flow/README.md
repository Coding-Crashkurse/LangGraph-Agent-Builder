# 01 · hello_flow

The canonical fixture (SPEC Appendix A): `start → Fake LLM → end`. No API keys.

**Shows:** validate / run / SSE basics.

```bash
# headless, no server:
lab flow validate examples/01_hello_flow/flow.json
lab flow run examples/01_hello_flow/flow.json --local --input "hi"
# → Hello from LAB!

# against a running server:
lab flow import examples/01_hello_flow/flow.json
lab flow publish hello
curl -N -X POST http://127.0.0.1:8000/api/v1/flows/<id>/run \
  -H 'Content-Type: application/json' \
  -d '{"input_text": "hi", "stream": true}'
```

Expected transcript: one `run_started`, `node_started/finished` per node, a
`fake.thinking` custom event, `run_finished` with `Hello from LAB!`.
