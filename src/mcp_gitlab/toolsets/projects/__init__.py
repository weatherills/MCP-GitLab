"""PRD-01 toolset `projects`: projects (repositories), branches, tags, and badges."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.projects.badges import BADGES_TOOL
from mcp_gitlab.toolsets.projects.branches import BRANCHES_TOOL
from mcp_gitlab.toolsets.projects.projects import PROJECTS_TOOL
from mcp_gitlab.toolsets.projects.tags import TAGS_TOOL

TOOLSET = Toolset(
    name="projects",
    description="Projects (repositories), branches, tags, and badges.",
    tools=(PROJECTS_TOOL, BRANCHES_TOOL, TAGS_TOOL, BADGES_TOOL),
)
