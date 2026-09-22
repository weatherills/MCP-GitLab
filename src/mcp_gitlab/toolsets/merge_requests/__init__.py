"""PRD-03 toolset `merge_requests`: merge requests, their review threads, and approvals."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.merge_requests.merge_requests import MERGE_REQUESTS_TOOL
from mcp_gitlab.toolsets.merge_requests.reviews import MR_REVIEWS_TOOL

TOOLSET = Toolset(
    name="merge_requests",
    description="Merge requests: lifecycle, diffs, merging, review threads, and approvals.",
    tools=(MERGE_REQUESTS_TOOL, MR_REVIEWS_TOOL),
)
