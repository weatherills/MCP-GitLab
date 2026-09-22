"""gitlab_jobs: jobs, their logs, and their artifacts, one file at a time (PRD-05 s.3-4)."""

import re
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from mcp_gitlab.core.errors import GitLabNotFoundError, PayloadTooLargeError
from mcp_gitlab.gitlab import Page, encode_wildcard_path, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef
from mcp_gitlab.toolsets.content import file_too_large, present

JobId = Annotated[int, Field(ge=1, description="Job ID.")]
JobStatus = Literal[
    "created",
    "pending",
    "running",
    "failed",
    "success",
    "canceled",
    "canceling",
    "skipped",
    "manual",
    "scheduled",
    "preparing",
    "waiting_for_resource",
    "waiting_for_callback",
]

DEFAULT_TAIL_LINES = 500
ARTIFACT_FILE_HINT = "Use list_artifacts to find a smaller file, or download the archive in GitLab."

# ANSI escape sequences (colors, cursor moves) and GitLab's collapsible-section markers.
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECTION_MARKER = re.compile(r"section_(?:start|end):\d+:[^\r\n\x1b]*")


class ListJobsParams(PageParams):
    project: ProjectRef
    pipeline_id: int = Field(ge=1, description="Pipeline whose jobs to list.")
    scope: list[JobStatus] | None = Field(
        default=None, description='Only jobs in these statuses, such as ["failed"].'
    )
    include_retried: bool | None = Field(
        default=None, description="Also list jobs that were retried; GitLab hides them by default."
    )


class JobParams(ActionParams):
    project: ProjectRef
    job_id: JobId


class JobLogParams(JobParams):
    tail_lines: int = Field(
        default=DEFAULT_TAIL_LINES,
        ge=1,
        le=10_000,
        description="How many lines to return: the last ones, or from offset when it is given.",
    )
    offset: int | None = Field(
        default=None, ge=0, description="First line to return, counting from 0."
    )
    full: bool = Field(
        default=False,
        description="Return the whole log instead (still capped at GITLAB_MAX_RESPONSE_BYTES).",
    )


class JobVariable(ActionParams):
    key: str = Field(min_length=1, description="Variable name.")
    value: str = Field(description="Variable value.")


class PlayJobParams(JobParams):
    variables: list[JobVariable] | None = Field(
        default=None, description="Variables for this manual job run."
    )


class ListArtifactsParams(JobParams, PageParams):
    path: str | None = Field(
        default=None, min_length=1, description="Directory inside the archive; the root if omitted."
    )
    recursive: bool | None = Field(default=None, description="List the whole subtree.")


class ArtifactFileParams(JobParams):
    artifact_path: str = Field(
        min_length=1, description="Path of one file inside the job's artifacts archive."
    )

    @field_validator("artifact_path")
    @classmethod
    def _relative(cls, value: str) -> str:
        encode_wildcard_path(value)  # raises for empty, "." or ".." segments
        return value.strip("/")


async def list_jobs(params: ListJobsParams, ctx: ActionContext) -> Page:
    query: dict[str, Any] = params.page_query()
    if params.scope:
        query["scope[]"] = list(params.scope)
    if params.include_retried is not None:
        query["include_retried"] = params.include_retried
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/pipelines/{params.pipeline_id}/jobs", params=query
    )


async def get_job(params: JobParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_job_path(params))


async def get_log(params: JobLogParams, ctx: ActionContext) -> Any:
    try:
        raw = await ctx.gitlab.get_bytes(f"{_job_path(params)}/trace", follow_redirects=True)
    except PayloadTooLargeError as exc:
        raise PayloadTooLargeError(
            f"Job {params.job_id}'s log is larger than GITLAB_MAX_RESPONSE_BYTES; read it in "
            "GitLab, or raise the limit.",
            details=exc.details,
        ) from exc
    lines = clean_log(raw.decode("utf-8", "replace")).split("\n")
    if params.full:
        start, chosen = 0, lines
    elif params.offset is not None:
        start = min(params.offset, len(lines))
        chosen = lines[start : start + params.tail_lines]
    else:
        start = max(0, len(lines) - params.tail_lines)
        chosen = lines[start:]
    return {
        "job_id": params.job_id,
        "total_lines": len(lines),
        "first_line": start,
        "returned_lines": len(chosen),
        "truncated": len(chosen) < len(lines),
        "log": "\n".join(chosen),
    }


async def retry_job(params: JobParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{_job_path(params)}/retry")


async def cancel_job(params: JobParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{_job_path(params)}/cancel")


async def play_job(params: PlayJobParams, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {}
    if params.variables:
        body["job_variables_attributes"] = [variable.model_dump() for variable in params.variables]
    return await ctx.gitlab.post(f"{_job_path(params)}/play", json_body=body or None)


async def list_artifacts(params: ListArtifactsParams, ctx: ActionContext) -> Any:
    query: dict[str, Any] = {**params.page_query(), "path": params.path}
    if params.recursive is not None:
        query["recursive"] = params.recursive
    try:
        return await ctx.gitlab.get_page(f"{_job_path(params)}/artifacts/tree", params=query)
    except GitLabNotFoundError:
        # Listing files inside the archive needs GitLab 18.8; before that, show the archives.
        job = await ctx.gitlab.get(_job_path(params))
        archives = job.get("artifacts") or []
        return {
            "items": archives,
            "note": "GitLab could not list files inside this job's artifacts (it needs GitLab "
            "18.8 or later, and the path must exist). These are the job's artifact archives; "
            "get_artifact_file still fetches a file by its path."
            if archives
            else "This job has no artifacts.",
        }


async def get_artifact_file(params: ArtifactFileParams, ctx: ActionContext) -> Any:
    limit = ctx.settings.gitlab_mcp_max_file_bytes
    try:
        data = await ctx.gitlab.get_bytes(
            f"{_job_path(params)}/artifacts/{encode_wildcard_path(params.artifact_path)}",
            max_bytes=limit,
            follow_redirects=True,
        )
    except PayloadTooLargeError as exc:
        raise file_too_large(params.artifact_path, limit, hint=ARTIFACT_FILE_HINT) from exc
    return {"artifact_path": params.artifact_path, "size": len(data), **present(data)}


def clean_log(text: str) -> str:
    """Render a CI log as a terminal would, without its escape codes and section markers."""
    text = _ANSI.sub("", _SECTION_MARKER.sub("", text)).replace("\r\n", "\n")
    # A bare carriage return redraws the line (progress bars): keep what is left visible.
    return "\n".join(
        next((part for part in reversed(line.split("\r")) if part), "") for line in text.split("\n")
    )


def _job_path(params: JobParams) -> str:
    return f"{project_path(params.project)}/jobs/{params.job_id}"


JOBS_TOOL = Tool(
    name="gitlab_jobs",
    title="GitLab CI/CD jobs",
    description=(
        "Inspect a pipeline's jobs, read their logs (the tail by default), retry, cancel, or "
        "start manual jobs, and read artifact files one at a time."
    ),
    actions=(
        Action("list", "List a pipeline's jobs.", ListJobsParams, list_jobs, Access.READ),
        Action("get", "Get one job.", JobParams, get_job, Access.READ),
        Action(
            "get_log",
            f"Read a job's log: the last {DEFAULT_TAIL_LINES} lines unless you ask otherwise, "
            "without color codes or section markers.",
            JobLogParams,
            get_log,
            Access.READ,
        ),
        Action("retry", "Retry a job.", JobParams, retry_job, Access.WRITE),
        Action("cancel", "Cancel a job.", JobParams, cancel_job, Access.WRITE),
        Action("play", "Start a manual job.", PlayJobParams, play_job, Access.WRITE),
        Action(
            "list_artifacts",
            "List the files in a job's artifacts archive.",
            ListArtifactsParams,
            list_artifacts,
            Access.READ,
        ),
        Action(
            "get_artifact_file",
            "Read one file from a job's artifacts (never the whole archive).",
            ArtifactFileParams,
            get_artifact_file,
            Access.READ,
        ),
    ),
)
