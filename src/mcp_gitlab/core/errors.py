"""Error taxonomy shared by every layer (PRD-00 section 10).

Every error carries a stable machine-readable `code`, a message, and whether
retrying later could succeed, so the caller (and the model behind it) can
decide what to do next.
"""

from collections.abc import Mapping
from typing import Any, ClassVar


class ToolError(Exception):
    code: ClassVar[str] = "tool_error"
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class UnknownToolError(ToolError):
    """No tool has this name; surfaced as a protocol error rather than a tool result."""

    code = "unknown_tool"


class InvalidArgumentsError(ToolError):
    code = "invalid_arguments"


class UnknownActionError(ToolError):
    code = "unknown_action"


class ConfirmationRequiredError(ToolError):
    code = "confirmation_required"


class ReadOnlyModeError(ToolError):
    code = "read_only_mode"


class ToolsetDisabledError(ToolError):
    code = "toolset_disabled"


class AuthenticationRequiredError(ToolError):
    code = "authentication_required"


class PayloadTooLargeError(ToolError):
    code = "payload_too_large"


class GitLabError(ToolError):
    code = "gitlab_error"

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.status = status

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        if self.status is not None:
            payload["status"] = self.status
        return payload


class GitLabBadRequestError(GitLabError):
    code = "gitlab_bad_request"


class GitLabUnauthorizedError(GitLabError):
    code = "gitlab_unauthorized"


class GitLabForbiddenError(GitLabError):
    code = "gitlab_forbidden"


class GitLabNotFoundError(GitLabError):
    code = "gitlab_not_found"


class GitLabConflictError(GitLabError):
    code = "gitlab_conflict"


class GitLabUnprocessableError(GitLabError):
    code = "gitlab_unprocessable"


class GitLabRateLimitedError(GitLabError):
    code = "gitlab_rate_limited"
    retryable = True


class GitLabServerError(GitLabError):
    code = "gitlab_server_error"
    retryable = True


class GitLabUnavailableError(GitLabError):
    code = "gitlab_unavailable"
    retryable = True


_ERRORS_BY_STATUS: dict[int, type[GitLabError]] = {
    400: GitLabBadRequestError,
    401: GitLabUnauthorizedError,
    403: GitLabForbiddenError,
    404: GitLabNotFoundError,
    409: GitLabConflictError,
    422: GitLabUnprocessableError,
    429: GitLabRateLimitedError,
}


def gitlab_error_type(status: int) -> type[GitLabError]:
    if status in _ERRORS_BY_STATUS:
        return _ERRORS_BY_STATUS[status]
    if status >= 500:
        return GitLabServerError
    return GitLabError
