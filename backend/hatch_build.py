"""Hatch build hook: bundle the built frontend into langgraph_agent_builder/_static (SPEC §2.5).

Resolution order for the frontend build:
1. ``LAB_FRONTEND_BUILD`` env — explicit path to a ready dist/ directory.
2. ``../frontend/dist`` — a pre-built dist next to the backend.
3. Build it: ``pnpm install && pnpm build`` (falls back to npm) in ``../frontend``.

Editable installs (``uv sync`` dev loop) skip the bundle entirely — the dev
server proxies to Vite instead. Wheel builds fail hard without a frontend
unless ``LAB_SKIP_FRONTEND=1`` (used only for backend-only test wheels).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

HERE = Path(__file__).parent
STATIC = HERE / "src" / "langgraph_agent_builder" / "_static"
FRONTEND = HERE.parent / "frontend"


def _try_build_frontend() -> Path | None:
    if not (FRONTEND / "package.json").exists():
        return None
    for tool in ("pnpm", "npm"):
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            subprocess.run([exe, "install"], cwd=FRONTEND, check=True)
            subprocess.run([exe, "run", "build"], cwd=FRONTEND, check=True)
            dist = FRONTEND / "dist"
            return dist if (dist / "index.html").exists() else None
        except subprocess.CalledProcessError:
            continue
    return None


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel":
            return
        if version == "editable":
            return
        dist: Path | None = None
        explicit = os.environ.get("LAB_FRONTEND_BUILD")
        if explicit and (Path(explicit) / "index.html").exists():
            dist = Path(explicit)
        elif (FRONTEND / "dist" / "index.html").exists():
            dist = FRONTEND / "dist"
        else:
            dist = _try_build_frontend()
        if dist is None:
            if os.environ.get("LAB_SKIP_FRONTEND") == "1":
                self.app.display_warning(
                    "langgraph-agent-builder: building wheel WITHOUT bundled frontend"
                )
                return
            raise RuntimeError(
                "No frontend build found. Build frontend/dist first, set "
                "LAB_FRONTEND_BUILD, or set LAB_SKIP_FRONTEND=1."
            )
        if STATIC.exists():
            shutil.rmtree(STATIC)
        shutil.copytree(dist, STATIC)
        build_data.setdefault("artifacts", []).append("src/langgraph_agent_builder/_static/**")

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        return
