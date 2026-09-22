"""Which tools and actions a request may see and call (PRD-00 sections 6 and 7.2)."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from mcp_gitlab.core.context import RequestContext
from mcp_gitlab.core.errors import (
    InvalidArgumentsError,
    ReadOnlyModeError,
    ToolsetDisabledError,
    UnknownActionError,
    UnknownToolError,
)
from mcp_gitlab.core.logging import log_event
from mcp_gitlab.tools.model import Access, Action, Tool, Toolset
from mcp_gitlab.tools.schema import build_input_schema

logger = logging.getLogger(__name__)

ALL_TOOLSETS = "all"

# GitLab enforces scopes itself on every call; these only decide what a token is shown.
DEFAULT_SCOPES: dict[Access, frozenset[str]] = {
    Access.READ: frozenset({"api", "read_api"}),
    Access.WRITE: frozenset({"api"}),
}


@dataclass(frozen=True, slots=True)
class ToolView:
    toolset: Toolset
    tool: Tool
    actions: tuple[Action, ...]


class ToolRegistry:
    def __init__(
        self, toolsets: Sequence[Toolset], *, server_allowlist: frozenset[str] | None = None
    ) -> None:
        self._toolsets: dict[str, Toolset] = {}
        self._tools: dict[str, tuple[Toolset, Tool]] = {}
        for toolset in toolsets:
            if toolset.name in self._toolsets:
                raise ValueError(f"Duplicate toolset '{toolset.name}'.")
            self._toolsets[toolset.name] = toolset
            for tool in toolset.tools:
                if tool.name in self._tools:
                    raise ValueError(f"Duplicate tool '{tool.name}'.")
                build_input_schema(tool, tool.actions)
                self._tools[tool.name] = (toolset, tool)
        self._server_allowlist = (
            None if server_allowlist is None else self._known(server_allowlist, strict=True)
        )

    @property
    def toolset_names(self) -> frozenset[str]:
        return frozenset(self._toolsets)

    def enabled_toolsets(self, request: RequestContext) -> frozenset[str]:
        """Operator allowlist is the ceiling; a client's X-MCP-Toolsets selects within it."""
        available = (
            self._server_allowlist if self._server_allowlist is not None else self.toolset_names
        )
        if request.requested_toolsets is not None:
            requested = self._known(request.requested_toolsets, strict=False)
        elif self._server_allowlist is not None:
            requested = self._server_allowlist
        else:
            requested = frozenset(
                name for name, toolset in self._toolsets.items() if toolset.default_enabled
            )
        return requested & available

    def visible(self, request: RequestContext, scopes: frozenset[str] | None) -> list[ToolView]:
        enabled = self.enabled_toolsets(request)
        views: list[ToolView] = []
        for toolset in self._toolsets.values():
            if toolset.name not in enabled:
                continue
            for tool in toolset.tools:
                actions = tuple(
                    action for action in tool.actions if _shown(action, request, scopes)
                )
                if actions:
                    views.append(ToolView(toolset, tool, actions))
        return views

    def resolve(
        self, tool_name: str, action_name: object, request: RequestContext
    ) -> tuple[Tool, Action]:
        entry = self._tools.get(tool_name)
        if entry is None:
            raise UnknownToolError(f"Unknown tool '{tool_name}'.")
        toolset, tool = entry
        if toolset.name not in self.enabled_toolsets(request):
            raise ToolsetDisabledError(
                f"Tool '{tool_name}' belongs to toolset '{toolset.name}', which is not enabled "
                "for this connection.",
                details={"toolset": toolset.name},
            )
        valid = [action.name for action in tool.actions]
        if not isinstance(action_name, str) or not action_name:
            raise InvalidArgumentsError(
                "Missing required argument 'action'.", details={"valid_actions": valid}
            )
        action = tool.action(action_name)
        if action is None:
            raise UnknownActionError(
                f"Tool '{tool_name}' has no action '{action_name}'.",
                details={"valid_actions": valid},
            )
        if request.read_only and action.access is Access.WRITE:
            raise ReadOnlyModeError(
                f"'{action_name}' writes to GitLab and this connection is read-only."
            )
        return tool, action

    def _known(self, names: frozenset[str], *, strict: bool) -> frozenset[str]:
        if ALL_TOOLSETS in names:
            return self.toolset_names
        unknown = names - self.toolset_names
        if unknown and strict:
            raise ValueError(
                f"GITLAB_MCP_TOOLSETS names unknown toolsets {sorted(unknown)}; "
                f"available: {sorted(self.toolset_names)}."
            )
        if unknown:
            log_event(
                logger, logging.WARNING, "unknown_toolsets_requested", toolsets=sorted(unknown)
            )
        return names & self.toolset_names


def _shown(action: Action, request: RequestContext, scopes: frozenset[str] | None) -> bool:
    if request.read_only and action.access is Access.WRITE:
        return False
    if scopes is None:
        return True
    return bool((action.scopes or DEFAULT_SCOPES[action.access]) & scopes)
