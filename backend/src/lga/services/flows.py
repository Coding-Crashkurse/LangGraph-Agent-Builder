"""Flow storage: drafts, immutable published versions, publish guards (SPEC §9.1)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import FlowRow, FlowVersionRow
from lga.schema.diagnostics import Diagnostic, DiagnosticCode, has_errors
from lga.schema.flowspec import FlowSpec, parse_flowspec
from lga.sdk.component import NodeKind

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump_semver(current: str, bump: str) -> str:
    match = SEMVER_RE.match(current or "0.0.0")
    major, minor, patch = (int(g) for g in match.groups()) if match else (0, 0, 0)
    if SEMVER_RE.match(bump):
        return bump
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def publish_guards(spec: FlowSpec, registry: Any) -> list[Diagnostic]:
    """E060–E063 (SPEC §7.4, §8.1)."""
    diags: list[Diagnostic] = []
    if spec.flow.a2a.enabled:
        if not (spec.flow.a2a.description or spec.flow.description):
            diags.append(
                Diagnostic.make(
                    DiagnosticCode.E060,
                    "A2A skill description is required before publishing with a2a.enabled",
                    fix_hint="Fill Flow Settings → A2A → description.",
                )
            )
        if not spec.flow.a2a.examples:
            diags.append(
                Diagnostic.make(
                    DiagnosticCode.E061,
                    "skill examples are recommended (agents route better with examples)",
                )
            )
    has_interrupt = False
    for node in spec.nodes:
        cls = registry.get(node.component_id)
        if cls is not None and cls.node_kind == NodeKind.INTERRUPT:
            has_interrupt = True
    if spec.flow.mcp.enabled:
        if not (spec.flow.mcp.description or spec.flow.description):
            diags.append(
                Diagnostic.make(
                    DiagnosticCode.E062,
                    "MCP tool description is required before publishing with mcp.enabled",
                    fix_hint="Fill Flow Settings → MCP → description.",
                )
            )
        if has_interrupt and spec.flow.mcp.auto_resolve_interrupts is None:
            diags.append(
                Diagnostic.make(
                    DiagnosticCode.E063,
                    "flow contains interrupt nodes; MCP has no input-required concept — "
                    "set mcp.auto_resolve_interrupts to approve|reject or disable MCP",
                )
            )
    return diags


class FlowService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    # ---------------------------------------------------------------- drafts
    async def create(self, spec: dict[str, Any] | FlowSpec) -> FlowRow:
        parsed = parse_flowspec(spec)
        row = FlowRow(
            slug=parsed.flow.slug,
            name=parsed.flow.name,
            description=parsed.flow.description,
            spec=parsed.model_dump(mode="json"),
        )
        async with self._sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def list(self) -> list[FlowRow]:
        async with self._sessions() as session:
            return list((await session.execute(select(FlowRow))).scalars().all())

    async def get(self, flow_id: str) -> FlowRow | None:
        async with self._sessions() as session:
            return await session.get(FlowRow, flow_id)

    async def get_by_slug(self, slug: str) -> FlowRow | None:
        async with self._sessions() as session:
            return (
                await session.execute(select(FlowRow).where(FlowRow.slug == slug))
            ).scalar_one_or_none()

    async def update(self, flow_id: str, spec: dict[str, Any] | FlowSpec) -> FlowRow | None:
        parsed = parse_flowspec(spec)
        async with self._sessions() as session:
            row = await session.get(FlowRow, flow_id)
            if row is None:
                return None
            row.slug = parsed.flow.slug
            row.name = parsed.flow.name
            row.description = parsed.flow.description
            row.spec = parsed.model_dump(mode="json")
            await session.commit()
            await session.refresh(row)
        return row

    async def set_serve_version(self, flow_id: str, serve: str) -> None:
        async with self._sessions() as session:
            row = await session.get(FlowRow, flow_id)
            if row is not None:
                row.serve_version = serve
                await session.commit()

    async def delete(self, flow_id: str) -> bool:
        async with self._sessions() as session:
            row = await session.get(FlowRow, flow_id)
            if row is None:
                return False
            await session.execute(delete(FlowVersionRow).where(FlowVersionRow.flow_id == flow_id))
            await session.delete(row)
            await session.commit()
            return True

    # ---------------------------------------------------------------- versions
    async def versions(self, flow_id: str) -> list[FlowVersionRow]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(FlowVersionRow)
                        .where(FlowVersionRow.flow_id == flow_id)
                        .order_by(FlowVersionRow.published_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            return list(rows)

    async def get_version(self, flow_id: str, semver: str) -> FlowVersionRow | None:
        async with self._sessions() as session:
            return (
                await session.execute(
                    select(FlowVersionRow).where(
                        FlowVersionRow.flow_id == flow_id, FlowVersionRow.semver == semver
                    )
                )
            ).scalar_one_or_none()

    async def latest_version(self, flow_id: str) -> FlowVersionRow | None:
        rows = await self.versions(flow_id)
        return rows[0] if rows else None

    async def serve_version(self, flow: FlowRow) -> FlowVersionRow | None:
        """The pinned published version an agent serves (SPEC §7.1)."""
        if flow.serve_version and flow.serve_version != "latest_published":
            return await self.get_version(flow.id, flow.serve_version)
        return await self.latest_version(flow.id)

    async def publish(
        self,
        flow_id: str,
        *,
        registry: Any,
        bump: str = "patch",
        changelog: str = "",
        compile_diagnostics: list[Diagnostic] | None = None,
    ) -> tuple[FlowVersionRow | None, list[Diagnostic]]:
        """Create an immutable version snapshot; blocked by ERROR diagnostics."""
        async with self._sessions() as session:
            row = await session.get(FlowRow, flow_id)
        if row is None:
            return None, [Diagnostic.make(DiagnosticCode.E001, f"flow {flow_id} not found")]
        spec = parse_flowspec(row.spec)
        diags = list(compile_diagnostics or [])
        diags += publish_guards(spec, registry)
        if has_errors(diags):
            return None, diags
        latest = await self.latest_version(flow_id)
        semver = bump_semver(latest.semver if latest else "0.0.0", bump)
        version = FlowVersionRow(
            flow_id=flow_id,
            semver=semver,
            flowspec=row.spec,
            changelog=changelog,
        )
        async with self._sessions() as session:
            session.add(version)
            await session.commit()
            await session.refresh(version)
        return version, diags

    async def rollback(self, flow_id: str, semver: str) -> FlowRow | None:
        version = await self.get_version(flow_id, semver)
        if version is None:
            return None
        return await self.update(flow_id, version.flowspec)

    # ---------------------------------------------------------------- serving helpers
    async def published_flows(self) -> list[tuple[FlowRow, FlowVersionRow, FlowSpec]]:
        """All flows with a published version whose spec enables A2A or MCP."""
        result: list[tuple[FlowRow, FlowVersionRow, FlowSpec]] = []
        for flow in await self.list():
            version = await self.serve_version(flow)
            if version is None:
                continue
            spec = parse_flowspec(version.flowspec)
            if spec.flow.a2a.enabled or spec.flow.mcp.enabled:
                result.append((flow, version, spec))
        return result
