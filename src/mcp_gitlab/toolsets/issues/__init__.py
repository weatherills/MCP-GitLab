"""PRD-04 toolset `issues`: issues, their comments, labels, and milestones."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.issues.issues import ISSUES_TOOL
from mcp_gitlab.toolsets.issues.labels import LABELS_TOOL
from mcp_gitlab.toolsets.issues.milestones import MILESTONES_TOOL
from mcp_gitlab.toolsets.issues.notes import ISSUE_NOTES_TOOL

TOOLSET = Toolset(
    name="issues",
    description="Issues and planning: issues, their comments, labels, and milestones.",
    tools=(ISSUES_TOOL, ISSUE_NOTES_TOOL, LABELS_TOOL, MILESTONES_TOOL),
)
