"""The tool framework's building blocks (PRD-00 section 6).

A `Toolset` (one per functional PRD) groups coarse `Tool`s. Each tool exposes
several `Action`s selected by an `action` argument, rather than one MCP tool per
GitLab REST endpoint.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mcp_gitlab.config import Settings
from mcp_gitlab.core.context import RequestContext
from mcp_gitlab.gitlab.client import GitLabSession

RESERVED_ARGUMENTS = frozenset({"action", "confirm"})
RESERVED_TOOLSET_NAMES = frozenset({"all"})

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class Access(str, Enum):
    READ = "read"
    WRITE = "write"


class ActionParams(BaseModel):
    """Base for action parameters: unknown arguments are rejected rather than ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoParams(ActionParams):
    pass


class PageParams(ActionParams):
    """Offset pagination shared by every list action (PRD-00 section 10)."""

    page: int = Field(default=1, ge=1, description="Page number, starting at 1.")
    per_page: int = Field(default=20, ge=1, le=100, description="Results per page, at most 100.")

    def page_query(self) -> dict[str, int]:
        return {"page": self.page, "per_page": self.per_page}


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Everything a handler may use; built per call and discarded afterwards."""

    request: RequestContext
    gitlab: GitLabSession
    settings: Settings


Handler = Callable[[Any, ActionContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    description: str
    params: type[ActionParams]
    handler: Handler
    access: Access
    destructive: bool = False
    scopes: frozenset[str] | None = None
    """GitLab token scopes that permit this action; None means the default for its access level."""

    def __post_init__(self) -> None:
        _check_name("action", self.name)
        if not issubclass(self.params, ActionParams):
            raise TypeError(f"Action '{self.name}': params must subclass ActionParams.")
        reserved = RESERVED_ARGUMENTS & set(self.params.model_fields)
        if reserved:
            raise ValueError(
                f"Action '{self.name}': parameter names {sorted(reserved)} are reserved."
            )
        if self.destructive and self.access is not Access.WRITE:
            raise ValueError(f"Action '{self.name}': only write actions can be destructive.")


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    actions: tuple[Action, ...]
    title: str | None = None

    def __post_init__(self) -> None:
        _check_name("tool", self.name)
        if not self.actions:
            raise ValueError(f"Tool '{self.name}' has no actions.")
        _check_unique(f"Tool '{self.name}' action", [action.name for action in self.actions])

    def action(self, name: str) -> Action | None:
        return next((action for action in self.actions if action.name == name), None)


@dataclass(frozen=True, slots=True)
class Toolset:
    name: str
    description: str
    tools: tuple[Tool, ...]
    default_enabled: bool = True
    """Enabled when neither GITLAB_MCP_TOOLSETS nor X-MCP-Toolsets selects toolsets explicitly."""

    def __post_init__(self) -> None:
        _check_name("toolset", self.name)
        if self.name in RESERVED_TOOLSET_NAMES:
            raise ValueError(f"Toolset name '{self.name}' is reserved.")
        if not self.tools:
            raise ValueError(f"Toolset '{self.name}' has no tools.")
        _check_unique(f"Toolset '{self.name}' tool", [tool.name for tool in self.tools])


def _check_name(kind: str, name: str) -> None:
    if not _NAME.match(name):
        raise ValueError(
            f"Invalid {kind} name '{name}': use lowercase snake_case, at most 64 characters."
        )


def _check_unique(kind: str, names: list[str]) -> None:
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"{kind} names must be unique; duplicated: {duplicates}.")
