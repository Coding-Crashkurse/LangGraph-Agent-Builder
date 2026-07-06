#!/usr/bin/env bash
# Import + test every example against the backend venv (SPEC §13).
# Examples 01/02/04/05/06/07/08/09/10 run key-free (fake_llm); 03 is
# marked `requires: [openai, postgres]` and only validates statically here.
set -euo pipefail
cd "$(dirname "$0")/../backend"
uv run pytest ../examples -q -p no:cacheprovider "$@"
