"""PRD-02 toolset `repository`: tree, files, directories, commits, and diffs."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.repository.commits import COMMITS_TOOL
from mcp_gitlab.toolsets.repository.files import FILES_TOOL
from mcp_gitlab.toolsets.repository.tree import TREE_TOOL

TOOLSET = Toolset(
    name="repository",
    description="Repository contents: tree, files, directories, commits, and diffs.",
    tools=(TREE_TOOL, FILES_TOOL, COMMITS_TOOL),
)
