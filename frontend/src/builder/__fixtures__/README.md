# Test fixtures

`node-types.json` is the real `GET /node-types` response, generated from the
backend catalog (which itself derives the JSON Schemas from agentplane-core
models). Config panel tests render against these schemas, never against
hand-written field lists (CLAUDE.md testing rules).

Regenerate after backend catalog changes:

```bash
cd backend && uv run python -c "
from langgraph_agent_builder.node_types import CATALOG
import pathlib
pathlib.Path('../frontend/src/builder/__fixtures__/node-types.json').write_text(
    CATALOG.model_dump_json(indent=2) + '\n', encoding='utf-8')
"
```
