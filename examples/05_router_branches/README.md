# 05 · router_branches

`LLM Router` (labels billing/bug/other — without a model it falls back to
deterministic keyword matching, so CI needs no keys) feeding a `Rule Router`
(`"asap" in message` → urgent) on the `other` lane.

**Shows:** ROUTER semantics (§5.5), dynamic ROUTE outputs from labels, rule
predicates, exactly-one-branch execution.

```bash
lga flow run examples/05_router_branches/flow.json --local --input "I found a bug"
# → Routed to BUG: filed in the tracker.
lga flow run examples/05_router_branches/flow.json --local --input "need help asap"
# → Routed to OTHER/URGENT: escalating now.
```
