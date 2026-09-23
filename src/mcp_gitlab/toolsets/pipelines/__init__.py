"""PRD-05 toolset `pipelines`: CI/CD pipelines, jobs, logs, artifacts, variables, schedules, and
runners."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.pipelines.jobs import JOBS_TOOL
from mcp_gitlab.toolsets.pipelines.pipelines import PIPELINES_TOOL
from mcp_gitlab.toolsets.pipelines.runners import RUNNERS_TOOL
from mcp_gitlab.toolsets.pipelines.schedules import PIPELINE_SCHEDULES_TOOL
from mcp_gitlab.toolsets.pipelines.variables import CI_VARIABLES_TOOL

TOOLSET = Toolset(
    name="pipelines",
    description="CI/CD: pipelines, jobs and their logs and artifacts, project variables, "
    "pipeline schedules, and runners.",
    tools=(PIPELINES_TOOL, JOBS_TOOL, CI_VARIABLES_TOOL, PIPELINE_SCHEDULES_TOOL, RUNNERS_TOOL),
)
