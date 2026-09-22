"""Presenting repository bytes to callers: text when it is UTF-8, base64 otherwise."""

import base64
from typing import Any

from mcp_gitlab.core.errors import PayloadTooLargeError


def present(data: bytes) -> dict[str, Any]:
    try:
        return {"encoding": "text", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


REPOSITORY_FILE_HINT = (
    "Read part of it with get_blame and range_start/range_end, or clone the repository."
)


def file_too_large(
    file_path: str, limit: int, size: int | None = None, *, hint: str = REPOSITORY_FILE_HINT
) -> PayloadTooLargeError:
    measured = f"is {size} bytes, " if size is not None else ""
    details: dict[str, Any] = {"max_bytes": limit}
    if size is not None:
        details["size"] = size
    return PayloadTooLargeError(
        f"'{file_path}' {measured}over the {limit}-byte limit (GITLAB_MCP_MAX_FILE_BYTES). {hint}",
        details=details,
    )
