"""Push notifications: DB config store + SSRF-guarded delivery (SPEC §7.9)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.tasks import (
    PushNotificationConfigStore,
    PushNotificationEvent,
    PushNotificationSender,
)
from a2a.types import TaskPushNotificationConfig
from a2a.utils.proto_utils import to_stream_response
from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from langgraph_agent_builder.a2a.tasks import TERMINAL_STATES, state_from_str
from langgraph_agent_builder.db.models import PushConfigRow
from langgraph_agent_builder.errors import LabValueError
from langgraph_agent_builder.services.settings import Settings

logger = logging.getLogger("langgraph_agent_builder.a2a.push")

# §7.9: input-required + terminal notify. The v1.0 protobuf TaskPushNotificationConfig
# has no metadata channel, so the old per-config `working` opt-in is no longer
# expressible — `working`/`submitted` never notify.
NOTIFY_STATES: set[int] = TERMINAL_STATES | {state_from_str("input-required")}
RETRIES = 3


class SsrfError(LabValueError):
    pass


def _check_scheme_policy(scheme: str, settings: Settings) -> None:
    if scheme not in ("http", "https"):
        raise SsrfError(f"unsupported scheme {scheme!r}")
    if settings.env == "prod" and scheme != "https" and not settings.a2a_allow_http:
        raise SsrfError("push webhooks must be https in prod")


def _ensure_global(host: str, addresses: Sequence[str]) -> None:
    """Reject every non-global address: `not is_global` also catches 0.0.0.0,
    reserved ranges and IPv6-mapped private forms that is_private/is_loopback
    miss. Multicast needs its own check — Python (per the IANA registry)
    reports 224.0.0.1/ff02::1 as `is_global=True`."""
    for raw in addresses:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise SsrfError(
                f"webhook host {host!r} resolves to a private address ({raw}); "
                "set LAB_PUSH_ALLOW_PRIVATE=true to allow (dev only)"
            )


def validate_webhook_url(url: str, settings: Settings) -> None:
    """https-only in prod; DNS-resolve and reject non-global ranges.

    Synchronous — this is the shared validator for the http_request/web_search
    components (§10.5). The push paths use :func:`resolve_and_pin_webhook`,
    which resolves off the event loop and pins the vetted address.
    """
    parsed = urlparse(url)
    _check_scheme_policy(parsed.scheme, settings)
    if settings.push_allow_private:
        return
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfError(f"cannot resolve webhook host {host!r}") from exc
    _ensure_global(host, [str(info[4][0]) for info in infos])


@dataclass(frozen=True)
class PinnedWebhook:
    """A vetted delivery target: connect to `url` (host replaced by the
    validated IP) while presenting the original host via Host/SNI."""

    url: str
    host_header: str
    sni_hostname: str | None


async def _resolve(host: str, port: int | None) -> list[str]:
    """DNS off the event loop (the loop resolver uses its default executor)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SsrfError(f"cannot resolve webhook host {host!r}") from exc
    return [str(info[4][0]) for info in infos]


async def resolve_and_pin_webhook(url: str, settings: Settings) -> PinnedWebhook | None:
    """Resolve once, validate, then connect to the validated address.

    Pinning closes the DNS-rebinding TOCTOU between our validation and httpx's
    own re-resolution at connect time (§7.9/§10.5). Returns None when
    `LAB_PUSH_ALLOW_PRIVATE` disables the guard (dev only): deliver unpinned.
    """
    parsed = urlparse(url)
    _check_scheme_policy(parsed.scheme, settings)
    if settings.push_allow_private:
        return None
    host = parsed.hostname or ""
    addresses = await _resolve(host, parsed.port)
    _ensure_global(host, addresses)
    ip = addresses[0]
    netloc = f"[{ip}]" if ":" in ip else ip
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return PinnedWebhook(
        url=urlunparse(parsed._replace(netloc=netloc)),
        host_header=f"{host}:{parsed.port}" if parsed.port else host,
        sni_hostname=host if parsed.scheme == "https" else None,
    )


def _event_state(event: PushNotificationEvent) -> int | None:
    """State carried by a task/status event; None for artifact-update events."""
    try:
        return int(event.status.state)  # Task, TaskStatusUpdateEvent
    except AttributeError:
        return None  # TaskArtifactUpdateEvent has no status


class DbPushConfigStore(PushNotificationConfigStore):
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def set_info(
        self,
        task_id: str,
        notification_config: TaskPushNotificationConfig,
        context: ServerCallContext | None = None,
    ) -> None:
        await resolve_and_pin_webhook(notification_config.url, self._settings)  # SSRF (§7.9)
        config_id = notification_config.id or task_id
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(PushConfigRow).where(
                        PushConfigRow.task_id == task_id, PushConfigRow.id == config_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = PushConfigRow(id=config_id, task_id=task_id, url=notification_config.url)
                session.add(row)
            row.url = notification_config.url
            row.token = notification_config.token or None
            row.config = MessageToDict(notification_config)
            await session.commit()

    async def get_info(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> list[TaskPushNotificationConfig]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(PushConfigRow).where(PushConfigRow.task_id == task_id)
                    )
                )
                .scalars()
                .all()
            )
        return [
            ParseDict(r.config, TaskPushNotificationConfig(), ignore_unknown_fields=True)
            for r in rows
        ]

    async def get_info_for_dispatch(self, task_id: str) -> list[TaskPushNotificationConfig]:
        """Out-of-band delivery lookup — no call context, fans across all owners."""
        return await self.get_info(task_id)

    async def delete_info(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
        config_id: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            stmt = delete(PushConfigRow).where(PushConfigRow.task_id == task_id)
            if config_id:
                stmt = stmt.where(PushConfigRow.id == config_id)
            await session.execute(stmt)
            await session.commit()


class GuardedPushSender(PushNotificationSender):
    """POSTs the task event with retries + client token header (SPEC §7.9).

    a2a-sdk 1.x drives ``send_notification(task_id, event)`` on every task event;
    we gate delivery to the §7.9 notify states and SSRF-pin each webhook.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        store: DbPushConfigStore,
        settings: Settings,
    ) -> None:
        self._client = client
        self._store = store
        self._settings = settings

    @staticmethod
    def _should_notify(state: int) -> bool:
        """The §7.9 decision: input-required + terminal notify; everything else
        (working, submitted, auth-required, artifact-update) never."""
        return state in NOTIFY_STATES

    async def send_notification(self, task_id: str, event: PushNotificationEvent) -> None:
        state = _event_state(event)
        if state is None or not self._should_notify(state):
            return
        configs = await self._store.get_info_for_dispatch(task_id)
        if not configs:
            return
        payload = MessageToDict(to_stream_response(event))
        for config in configs:
            try:
                pinned = await resolve_and_pin_webhook(config.url, self._settings)
            except SsrfError as exc:
                logger.warning("push blocked for task %s: %s", task_id, exc)
                continue
            await self._deliver(task_id, config, pinned, payload)

    async def _deliver(
        self,
        task_id: str,
        config: TaskPushNotificationConfig,
        pinned: PinnedWebhook | None,
        payload: dict[str, Any],
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if config.token:
            headers["X-A2A-Notification-Token"] = config.token
        url = config.url
        extensions: dict[str, Any] | None = None
        if pinned is not None:
            url = pinned.url
            headers["Host"] = pinned.host_header
            if pinned.sni_hostname:
                extensions = {"sni_hostname": pinned.sni_hostname}
        for attempt in range(RETRIES):
            try:
                response = await self._client.post(
                    url, json=payload, headers=headers, timeout=10.0, extensions=extensions
                )
                response.raise_for_status()
                return
            except Exception as exc:
                if attempt == RETRIES - 1:
                    logger.warning(
                        "push delivery failed for task %s → %s: %s",
                        task_id,
                        config.url,
                        exc,
                    )
                else:
                    await asyncio.sleep(0.5 * 2**attempt)
