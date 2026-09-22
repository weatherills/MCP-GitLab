"""PRD-06 toolset `releases`: releases and their asset links."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.releases.links import RELEASE_LINKS_TOOL
from mcp_gitlab.toolsets.releases.releases import RELEASES_TOOL

TOOLSET = Toolset(
    name="releases",
    description="Releases: notes and metadata on top of tags, and their asset links.",
    tools=(RELEASES_TOOL, RELEASE_LINKS_TOOL),
)
