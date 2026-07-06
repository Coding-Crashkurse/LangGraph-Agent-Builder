# 04 · hitl_approval_a2a

`start → Fake LLM (draft) → Human Approval → end` (reject loops back for a new
draft). The flagship feature (SPEC §7.7): a canvas Human Approval node becomes
a protocol-level A2A `input-required` interaction.

```bash
lga run &                            # or: lga run in another terminal
lga flow import examples/04_hitl_approval_a2a/flow.json
lga flow publish hitl-approval
python examples/04_hitl_approval_a2a/client.py
# task … → input-required
# agent asks: Release this answer?  options=['approve', 'reject']
# approve/reject> approve
# task → completed
# artifact: Draft: we will refund the order.
```
