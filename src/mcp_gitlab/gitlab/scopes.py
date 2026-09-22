"""Token scope lookup for scope-aware tool visibility (PRD-00 section 7.2)."""

import logging

from mcp_gitlab.core.errors import GitLabError
from mcp_gitlab.core.logging import log_event
from mcp_gitlab.gitlab.client import GitLabSession

logger = logging.getLogger(__name__)


async def resolve_token_scopes(session: GitLabSession) -> frozenset[str] | None:
    """The token's scopes, or None when they can't be determined.

    Visibility filtering is a convenience, not a security boundary (GitLab
    enforces scopes on every call), so any failure here hides nothing.
    """
    try:
        data = await session.get("/personal_access_tokens/self")
    except GitLabError as exc:
        log_event(
            logger, logging.WARNING, "token_scope_lookup_failed", code=exc.code, status=exc.status
        )
        return None
    scopes = data.get("scopes") if isinstance(data, dict) else None
    if not isinstance(scopes, list):
        return None
    return frozenset(str(scope) for scope in scopes)
