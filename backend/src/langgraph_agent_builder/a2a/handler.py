"""LabRequestHandler — the A2A request handler (SPEC §7).

In a2a-sdk 1.x (protocol v1.0) the two behaviors this class carried on 0.3 are
now native to ``DefaultRequestHandler`` (``DefaultRequestHandlerV2``), so there
is nothing left to override:

- **push-capability honesty (§7.9/§7.10):** every ``tasks/pushNotificationConfig/*``
  method is gated by ``@validate(... capabilities.push_notifications,
  error_type=PushNotificationNotSupportedError)``. When the agent card advertises
  ``pushNotifications: false`` (see ``a2a/card.py`` + ``a2a/mount.py``, which wire
  no push store/sender in that case) the handler raises
  ``PushNotificationNotSupportedError`` → HTTP 400 / ``FAILED_PRECONDITION`` /
  ``PUSH_NOTIFICATION_NOT_SUPPORTED``. The 0.3 custom gate + ``LabJSONRPCHandler``
  (which forced -32003 over the JSON-RPC ``@validate`` default) are obsolete.

- **resubscribe replay (§7.5):** ``on_subscribe_to_task`` calls
  ``ActiveTask.subscribe(include_initial_task=True)``, which yields the persisted
  ``Task`` snapshot as the first stream event and raises ``InvalidParamsError``
  for finished/terminal tasks. The 0.3 manual snapshot-replay + watchdog +
  store-fallback are gone (v1.0's queue manager taps a live, replayed stream and
  no longer wipes tapped child queues on immediate close).

Kept as a named seam so flow-specific request handling has a stable place to
land without touching mount.py again.
"""

from __future__ import annotations

from a2a.server.request_handlers import DefaultRequestHandler


class LabRequestHandler(DefaultRequestHandler):
    """A2A request handler; behavior is the SDK default (see module docstring)."""
