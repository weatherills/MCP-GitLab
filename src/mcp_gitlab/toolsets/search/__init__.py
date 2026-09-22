"""PRD-07 toolset `search`: instance, group, and project search."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.search.search import SEARCH_TOOL

TOOLSET = Toolset(
    name="search",
    description="Search across the instance, a group, or a project, with compact results.",
    tools=(SEARCH_TOOL,),
)
