"""Secret scrubbing for events & logs (SPEC §10.5)."""

from __future__ import annotations

import logging

from lga.runtime.streams import EventBus
from lga.schema.events import RunEvent
from lga.schema.scrub import (
    SecretScrubFilter,
    register_secret,
    scrub_data,
    scrub_text,
)


def test_scrub_text_redacts_known_secret() -> None:
    register_secret("hunter2-super-secret-value")
    assert scrub_text("token is hunter2-super-secret-value done") == "token is *** done"


def test_scrub_text_redacts_credential_shapes() -> None:
    assert "sk-" not in scrub_text("key=sk-" + "A" * 32)
    assert scrub_text("Authorization: Bearer " + "a" * 30).endswith("***")
    assert "AKIA" not in scrub_text("AKIAIOSFODNN7EXAMPLE here")


def test_scrub_text_leaves_normal_text_untouched() -> None:
    text = "the quick brown fox jumps over 12 lazy dogs"
    assert scrub_text(text) == text


def test_scrub_data_is_recursive() -> None:
    register_secret("p@ssw0rd-registered")
    out = scrub_data(
        {"a": "p@ssw0rd-registered", "b": ["ok", {"c": "p@ssw0rd-registered"}], "n": 5}
    )
    assert out == {"a": "***", "b": ["ok", {"c": "***"}], "n": 5}


def test_event_bus_scrubs_known_secret() -> None:
    register_secret("leaked-secret-abcdef123456")
    bus = EventBus()  # no persist → publish is fully synchronous
    event = RunEvent(
        event="node_log",
        run_id="r1",
        thread_id="t1",
        data={"msg": "connecting with leaked-secret-abcdef123456"},
    )
    out = bus.publish(event)
    assert "leaked-secret-abcdef123456" not in str(out.data)
    assert out.data["msg"] == "connecting with ***"


def test_log_filter_scrubs_message() -> None:
    register_secret("logged-secret-abcdef123456")
    record = logging.LogRecord(
        name="lga.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="using %s now",
        args=("logged-secret-abcdef123456",),
        exc_info=None,
    )
    assert SecretScrubFilter().filter(record) is True
    assert "logged-secret-abcdef123456" not in record.getMessage()
    assert "***" in record.getMessage()
