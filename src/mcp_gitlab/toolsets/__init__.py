"""Registered toolsets: each functional PRD (PRD-01 to PRD-08) adds exactly one here."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets import projects, repository

TOOLSETS: tuple[Toolset, ...] = (projects.TOOLSET, repository.TOOLSET)
