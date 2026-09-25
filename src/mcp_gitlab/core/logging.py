"""Structured logging with request-id propagation and secret redaction (PRD-00 section 11)."""

import json
import logging
import re
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Literal

REDACTED = "[REDACTED]"

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})

_request_id: ContextVar[str | None] = ContextVar("mcp_gitlab_request_id", default=None)

# Defense in depth: nothing should log a token in the first place.
_SECRET_PATTERNS = (
    re.compile(r"\bgl[a-z]{2,8}-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/\-]+=*"),
    re.compile(r"(?i)\b(private-token[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]+"),
)

_RESERVED_KEYS = frozenset({"ts", "level", "logger", "message", "request_id", "exception"})


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) if match.re.groups else "") + REDACTED, text
        )
    return text


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})


def log_settings_from_env(env: Mapping[str, str]) -> tuple[str, Literal["json", "text"]]:
    """LOG_LEVEL and LOG_FORMAT read directly from the environment.

    For entrypoints that must log before (or without) building a full `Settings()` — this
    server's own settings validation needs GitLab and MCP configuration unrelated to logging.
    """
    level = env.get("LOG_LEVEL", "").upper()
    fmt: Literal["json", "text"] = "text" if env.get("LOG_FORMAT", "").lower() == "text" else "json"
    return (level if level in _LOG_LEVELS else "INFO"), fmt


def configure_logging(level: str = "INFO", fmt: Literal["json", "text"] = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            key: _redact_value(value)
            for key, value in _fields(record).items()
            if key not in _RESERVED_KEYS
        }
        entry["ts"] = _timestamp(record)
        entry["level"] = record.levelname
        entry["logger"] = record.name
        entry["message"] = redact(record.getMessage())
        request_id = current_request_id()
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        parts = [
            _timestamp(record),
            f"{record.levelname:<7}",
            f"{record.name}:",
            redact(record.getMessage()),
        ]
        request_id = current_request_id()
        if request_id:
            parts.append(f"request_id={request_id}")
        parts.extend(f"{key}={_redact_value(value)}" for key, value in _fields(record).items())
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + redact(self.formatException(record.exc_info))
        return line


def _fields(record: logging.LogRecord) -> Mapping[str, Any]:
    fields = getattr(record, "fields", None)
    return fields if isinstance(fields, Mapping) else {}


def _redact_value(value: Any) -> Any:
    return redact(value) if isinstance(value, str) else value


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    )
