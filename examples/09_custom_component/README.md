# 09 · custom_component

A real installable component package (`pkg/`) with an entry point — no
string-eval, ever (SPEC §4.8). It ships a **custom port schema**
(`ticket_triage:TicketBatch`) proving structural typing: `Ticket Parser`'s
batch output connects to `Ticket Summary`, while wiring it into, say, a
Message input is rejected at validate time with **E020** naming both
schema_refs.

```bash
uv pip install -e examples/09_custom_component/pkg
lab run    # sidebar now shows Ticket Parser + Ticket Summary
```

Scaffold your own with `lab component new my_component`.
