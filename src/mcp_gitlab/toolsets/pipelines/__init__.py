"""PRD-05 toolset `pipelines`: CI/CD pipelines, jobs, logs, artifacts, and variables."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.pipelines.jobs import JOBS_TOOL
from mcp_gitlab.toolsets.pipelines.pipelines import PIPELINES_TOOL
from mcp_gitlab.toolsets.pipelines.variables import CI_VARIABLES_TOOL

TOOLSET = Toolset(
    name="pipelines",
    description="CI/CD: pipelines, jobs and their logs and artifacts, and project variables.",
    tools=(PIPELINES_TOOL, JOBS_TOOL, CI_VARIABLES_TOOL),
)
