"""Unit tests for lga.schema.scrub — error/branch paths (SPEC §10.5)."""

from __future__ import annotations

import logging

from lga.schema.scrub import (
    REDACTED,
    SecretScrubFilter,
    install_log_scrubbing,
    register_secret,
    scrub_data,
    scrub_text,
)


def test_register_secret_ignores_too_short_value() -> None:
    # Below _MIN_KNOWN_LEN (6): must NOT be registered, so it survives scrubbing.
    register_secret("abc")
    assert scrub_text("value abc here") == "value abc here"


def test_register_secret_ignores_none_and_empty() -> None:
    register_secret(None)
    register_secret("")
    # Neither should have been added; a plain word stays intact.
    assert scrub_text("nothing to redact") == "nothing to redact"


def test_scrub_data_passes_through_non_string_scalars() -> None:
    assert scrub_data(5) == 5
    assert scrub_data(None) is None
    assert scrub_data(True) is True


def test_scrub_data_recurses_into_dict() -> None:
    register_secret("dict-secret-value")
    out = scrub_data({"outer": {"inner": "dict-secret-value"}, "keep": 1})
    assert out == {"outer": {"inner": REDACTED}, "keep": 1}


def test_scrub_data_preserves_tuple_type() -> None:
    register_secret("tuple-secret-value")
    out = scrub_data(("keep", "tuple-secret-value"))
    assert isinstance(out, tuple)
    assert out == ("keep", REDACTED)


def test_log_filter_returns_true_when_message_unchanged() -> None:
    record = logging.LogRecord(
        name="lga.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain harmless message",
        args=(),
        exc_info=None,
    )
    filt = SecretScrubFilter()
    assert filt.filter(record) is True
    # No secret present → msg/args left untouched.
    assert record.msg == "plain harmless message"
    assert record.getMessage() == "plain harmless message"


def test_log_filter_survives_bad_format_args() -> None:
    # getMessage() raises TypeError ("%d" % ("x",)); filter must swallow it.
    record = logging.LogRecord(
        name="lga.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%d",
        args=("not-an-int",),
        exc_info=None,
    )
    assert SecretScrubFilter().filter(record) is True


def test_install_log_scrubbing_is_idempotent() -> None:
    logger = logging.getLogger("lga.test.install")
    logger.handlers = [logging.StreamHandler()]
    install_log_scrubbing(logger)
    install_log_scrubbing(logger)  # second call must not add a duplicate filter
    handler = logger.handlers[0]
    scrub_filters = [f for f in handler.filters if isinstance(f, SecretScrubFilter)]
    assert len(scrub_filters) == 1


def test_install_log_scrubbing_scrubs_records_through_handler() -> None:
    register_secret("installed-secret-abcdef")
    logger = logging.getLogger("lga.test.install2")
    handler = logging.StreamHandler()
    logger.handlers = [handler]
    install_log_scrubbing(logger)
    record = logging.LogRecord(
        name="lga.test.install2",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="key=installed-secret-abcdef",
        args=(),
        exc_info=None,
    )
    installed = handler.filters[0]
    assert isinstance(installed, SecretScrubFilter)
    installed.filter(record)
    assert record.getMessage() == "key=***"
