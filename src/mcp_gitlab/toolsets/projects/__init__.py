"""PRD-01 toolset `projects`: projects (repositories), branches, and tags."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.projects.branches import BRANCHES_TOOL
from mcp_gitlab.toolsets.projects.projects import PROJECTS_TOOL
from mcp_gitlab.toolsets.projects.tags import TAGS_TOOL

TOOLSET = Toolset(
    name="projects",
    description="Projects (repositories), branches, and tags.",
    tools=(PROJECTS_TOOL, BRANCHES_TOOL, TAGS_TOOL),
)
