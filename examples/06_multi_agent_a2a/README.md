# 06 · multi_agent_a2a

An orchestrator flow that calls the example-04 agent (`hitl-approval`) as an
**A2A Remote Agent** node. The remote agent's `input-required` **propagates**:
the orchestrator raises its own interrupt mirroring the remote prompt, your
answer is forwarded to the remote task, and both flows complete (SPEC §7.12).

```bash
lga run &
lga flow import examples/04_hitl_approval_a2a/flow.json examples/06_multi_agent_a2a/flow.json
lga flow publish hitl-approval && lga flow publish orchestrator
python examples/04_hitl_approval_a2a/client.py http://127.0.0.1:8000 orchestrator
# the approval prompt you see comes from the NESTED agent, tunnelled through
# the orchestrator — answer `approve` and the artifact bubbles back up.
```

Note: `agent_url` in flow.json points at `127.0.0.1:8000`; adjust (or tweak at
run time) if your server runs elsewhere.
