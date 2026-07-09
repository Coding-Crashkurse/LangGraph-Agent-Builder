"""Push notifications: DB config store + SSRF-guarded delivery (SPEC §7.9)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.tasks import PushNotificationConfigStore, PushNotificationSender
from a2a.types import PushNotificationConfig, Task, TaskState
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lga.db.models import PushConfigRow
from lga.errors import LgaValueError
from lga.services.settings import Settings

logger = logging.getLogger("lga.a2a.push")

NOTIFY_STATES = {
    TaskState.input_required,
    TaskState.completed,
    TaskState.failed,
    TaskState.canceled,
    TaskState.rejected,
}
RETRIES = 3


class SsrfError(LgaValueError):
    pass


def validate_webhook_url(url: str, settings: Settings) -> None:
    """https-only in prod; DNS-resolve and reject private/link-local ranges."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"unsupported scheme {parsed.scheme!r}")
    if settings.env == "prod" and parsed.scheme != "https" and not settings.a2a_allow_http:
        raise SsrfError("push webhooks must be https in prod")
    if settings.push_allow_private:
        return
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfError(f"cannot resolve webhook host {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise SsrfError(
                f"webhook host {host!r} resolves to a private address ({ip}); "
                "set LGA_PUSH_ALLOW_PRIVATE=true to allow (dev only)"
            )


class DbPushConfigStore(PushNotificationConfigStore):
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def set_info(
        self,
        task_id: str,
        notification_config: PushNotificationConfig,
        context: ServerCallContext | None = None,
    ) -> None:
        validate_webhook_url(notification_config.url, self._settings)
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
            row.token = notification_config.token
            row.config = notification_config.model_dump(mode="json", exclude_none=True)
            await session.commit()

    async def get_info(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> list[PushNotificationConfig]:
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
        return [PushNotificationConfig.model_validate(r.config) for r in rows]

    async def delete_info(
        self,
        task_id: str,
        config_id: str | None = None,
        context: ServerCallContext | None = None,
    ) -> None:
        async with self._sessions() as session:
            stmt = delete(PushConfigRow).where(PushConfigRow.task_id == task_id)
            if config_id:
                stmt = stmt.where(PushConfigRow.id == config_id)
            await session.execute(stmt)
            await session.commit()


class GuardedPushSender(PushNotificationSender):
    """POSTs the Task object with retries + client token header (SPEC §7.9)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        store: DbPushConfigStore,
        settings: Settings,
    ) -> None:
        self._client = client
        self._store = store
        self._settings = settings

    async def send_notification(self, task: Task) -> None:
        state = task.status.state
        configs = await self._store.get_info(task.id)
        if not configs:
            return
        notify = state in NOTIFY_STATES or any(
            (c.model_dump().get("metadata") or {}).get("notify_working")
            for c in configs
            if hasattr(c, "metadata")
        )
        if not notify and state != TaskState.working:
            return
        if state == TaskState.working and not any(
            (getattr(c, "metadata", None) or {}).get("notify_working") for c in configs
        ):
            return
        payload = task.model_dump(mode="json", exclude_none=True)
        for config in configs:
            try:
                validate_webhook_url(config.url, self._settings)
            except SsrfError as exc:
                logger.warning("push blocked for task %s: %s", task.id, exc)
                continue
            headers = {"Content-Type": "application/json"}
            if config.token:
                headers["X-A2A-Notification-Token"] = config.token
            for attempt in range(RETRIES):
                try:
                    response = await self._client.post(
                        config.url, json=payload, headers=headers, timeout=10.0
                    )
                    response.raise_for_status()
                    break
                except Exception as exc:
                    if attempt == RETRIES - 1:
                        logger.warning(
                            "push delivery failed for task %s → %s: %s",
                            task.id,
                            config.url,
                            exc,
                        )
                    else:
                        await asyncio.sleep(0.5 * 2**attempt)
