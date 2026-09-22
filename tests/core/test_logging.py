import json
import logging

import pytest

from mcp_gitlab.core.logging import (
    REDACTED,
    JsonFormatter,
    TextFormatter,
    bind_request_id,
    current_request_id,
    log_event,
    redact,
)


@pytest.mark.parametrize(
    ("raw", "leaked"),
    [
        ("token glpat-abcdefghijklmnopqrstu used", "glpat-abcdefghijklmnopqrstu"),
        ("Authorization: Bearer glpat-xyz0123456789abcdef", "glpat-xyz0123456789abcdef"),
        ("Authorization: Bearer opaque.jwt-token_value", "opaque.jwt-token_value"),
        ("PRIVATE-TOKEN: secret-value", "secret-value"),
        ('{"private-token": "abc123"}', "abc123"),
    ],
)
def test_redact_removes_secrets(raw: str, leaked: str) -> None:
    cleaned = redact(raw)
    assert leaked not in cleaned
    assert REDACTED in cleaned


def test_redact_leaves_ordinary_text_alone() -> None:
    assert redact("GET /projects/42/repository/tree 200") == "GET /projects/42/repository/tree 200"


def _record(logger_name: str = "test") -> logging.LogRecord:
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    logger = logging.getLogger(logger_name)
    logger.propagate = False
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        log_event(
            logger,
            logging.INFO,
            "gitlab_request",
            method="GET",
            status=200,
            token="glpat-abcdefghijklmnopqrstu",
        )
    finally:
        logger.removeHandler(handler)
    return captured[0]


def test_json_formatter_includes_fields_and_request_id() -> None:
    record = _record()
    with bind_request_id("req-1"):
        entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "gitlab_request"
    assert entry["method"] == "GET"
    assert entry["status"] == 200
    assert entry["request_id"] == "req-1"
    assert entry["token"] == REDACTED


def test_fields_cannot_override_core_keys() -> None:
    record = _record()
    record.fields = {"level": "FAKE", "message": "spoofed"}
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "INFO"
    assert entry["message"] == "gitlab_request"


def test_text_formatter_renders_key_values() -> None:
    line = TextFormatter().format(_record())
    assert "gitlab_request" in line
    assert "method=GET" in line
    assert "glpat-" not in line


def test_request_id_is_scoped() -> None:
    assert current_request_id() is None
    with bind_request_id("outer"):
        with bind_request_id("inner"):
            assert current_request_id() == "inner"
        assert current_request_id() == "outer"
    assert current_request_id() is None
