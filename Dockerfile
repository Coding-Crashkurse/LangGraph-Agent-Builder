# syntax=docker/dockerfile:1

# Stage 1: build the SPA. The repo ships pnpm-lock.yaml (lockfileVersion 9) and
# a pnpm-workspace.yaml, so pnpm is the package manager — npm is only the
# hatch_build.py fallback for wheel builds.
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
RUN npm install -g pnpm@10
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

# Stage 2: install the backend with uv against its committed lockfile, then
# drop the built SPA onto the exact path the app serves it from.
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# Dependency layer first (cache-friendly): lockfile + project metadata only.
COPY backend/pyproject.toml backend/uv.lock backend/hatch_build.py backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# The project itself. uv installs it editable, so hatch_build.py skips the
# frontend bundle (version == "editable") and the package lives under ./src.
COPY backend/src ./src
RUN uv sync --frozen --no-dev

# app.py:_static_dir() serves Path(__file__).parent / "_static" when
# BUILDER_FRONTEND_PATH is unset — for the editable install that is exactly
# src/langgraph_agent_builder/_static.
COPY --from=frontend /app/frontend/dist ./src/langgraph_agent_builder/_static

# Non-root user; BUILDER_HOME=/data holds the SQLite drafts DB (mount a volume
# at /data to persist flows across container restarts).
RUN useradd --create-home --uid 1000 builder \
    && mkdir -p /data \
    && chown builder:builder /data

ENV PATH="/app/backend/.venv/bin:${PATH}" \
    BUILDER_ENV=prod \
    BUILDER_HOST=0.0.0.0 \
    BUILDER_PORT=8010 \
    BUILDER_HOME=/data

USER builder
EXPOSE 8010

# /api/v1/health is a real liveness route (api/config.py). python:3.12-slim
# ships no curl/wget, so probe with the stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c 'import os, urllib.request; urllib.request.urlopen("http://127.0.0.1:" + os.environ.get("BUILDER_PORT", "8010") + "/api/v1/health", timeout=4)'

CMD ["lab", "serve"]
