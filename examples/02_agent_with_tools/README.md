# 02 · agent_with_tools

`start → LLM Agent ⟵(dashed tool edges)⟵ Calculator, HTTP Request → end`.

**Shows:** tool edges (§4.4), node-as-tool wrapping (§4.7), the agent tool loop.

The checked-in flow uses the `fake` provider so CI needs no keys; the fake
model never emits tool calls, but the compile report proves the binding
(`tool_bindings.agent = [calculator, http_request]`). Swap `model` to
`{"provider": "openai", "model": "gpt-4o-mini"}` for a live agent:

```bash
LGA_CRED_OPENAI_API_KEY=sk-… lga flow run examples/02_agent_with_tools/flow.json \
  --local --input "what is (2+3)*4?"
```
