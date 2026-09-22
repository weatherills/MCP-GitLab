"""Per-request caller context, derived purely from HTTP headers.

This server is a shared resource, so it has no credentials of its own: every
request must carry its caller's GitLab PAT, which is used for that request only
and never stored, cached, or reused (the MCP authorization spec likewise
requires clients to send credentials on every HTTP request).
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from mcp_gitlab.config import Settings

TOOLSETS_HEADER = "x-mcp-toolsets"
READ_ONLY_HEADER = "x-mcp-readonly"
REQUEST_ID_HEADER = "x-request-id"

MISSING_TOKEN_MESSAGE = (
    "No GitLab token supplied: send 'Authorization: Bearer <PAT>' or 'PRIVATE-TOKEN: <PAT>'."
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


@dataclass(frozen=True, slots=True)
class Credentials:
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    credentials: Credentials | None
    requested_toolsets: frozenset[str] | None
    read_only: bool


def extract_credentials(headers: Mapping[str, str]) -> Credentials | None:
    """The PAT this request carries: `Authorization: Bearer`, else `PRIVATE-TOKEN`."""
    authorization = _header(headers, "authorization")
    if authorization:
        scheme, _, value = authorization.strip().partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return Credentials(value.strip())
    private_token = (_header(headers, "private-token") or "").strip()
    return Credentials(private_token) if private_token else None


def build_request_context(headers: Mapping[str, str], settings: Settings) -> RequestContext:
    return RequestContext(
        request_id=_request_id(_header(headers, REQUEST_ID_HEADER)),
        credentials=extract_credentials(headers),
        requested_toolsets=_parse_toolsets(_header(headers, TOOLSETS_HEADER)),
        # A client may opt into read-only mode, but can never lift the operator's.
        read_only=settings.gitlab_mcp_read_only
        or (_header(headers, READ_ONLY_HEADER) or "").strip().lower() in _TRUTHY,
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is not None:
        return value
    for key, candidate in headers.items():
        if key.lower() == name:
            return candidate
    return None


def _parse_toolsets(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    names = frozenset(part.strip().lower() for part in value.split(",") if part.strip())
    return names or None


def _request_id(inbound: str | None) -> str:
    """Reuse an upstream X-Request-ID for cross-service tracing when it is safe to log."""
    if inbound and _SAFE_REQUEST_ID.match(inbound):
        return inbound
    return uuid.uuid4().hex
