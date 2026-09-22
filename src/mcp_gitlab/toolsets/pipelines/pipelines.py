"""gitlab_pipelines: list, inspect, run, retry, cancel, and delete pipelines (PRD-05 s.3)."""

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp_gitlab.core.errors import GitLabForbiddenError
from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, Ref, query, with_hint

PipelineId = Annotated[int, Field(ge=1, description="Pipeline ID.")]
# GitLab's own status values, passed through unchanged (PRD-05 section 4).
PipelineStatus = Literal[
    "created",
    "waiting_for_resource",
    "preparing",
    "waiting_for_callback",
    "pending",
    "running",
    "success",
    "failed",
    "canceling",
    "canceled",
    "skipped",
    "manual",
    "scheduled",
]


class PipelineVariable(ActionParams):
    key: str = Field(min_length=1, description="Variable name.")
    value: str = Field(description="Variable value.")
    variable_type: Literal["env_var", "file"] | None = Field(
        default=None, description="env_var (the default) or file."
    )


class ListPipelinesParams(PageParams):
    project: ProjectRef
    status: PipelineStatus | None = Field(
        default=None, description="Only pipelines in this status."
    )
    ref: str | None = Field(default=None, min_length=1, description="Only this branch or tag.")
    sha: str | None = Field(default=None, min_length=1, description="Only this commit.")
    source: str | None = Field(
        default=None,
        min_length=1,
        description="Only pipelines from this source, such as push, web, merge_request_event, "
        "or schedule.",
    )


class PipelineParams(ActionParams):
    project: ProjectRef
    pipeline_id: PipelineId


class CreatePipelineParams(ActionParams):
    project: ProjectRef
    ref: Ref = Field(description="Branch or tag to run the pipeline on.")
    variables: list[PipelineVariable] | None = Field(
        default=None, description="Variables for this pipeline run."
    )


async def list_pipelines(params: ListPipelinesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/pipelines", params=query(params)
    )


async def get_pipeline(params: PipelineParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_pipeline_path(params))


async def create_pipeline(params: CreatePipelineParams, ctx: ActionContext) -> Any:
    # The caller's own PAT runs the pipeline; trigger tokens are out of scope (PRD-05 s.5).
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/pipeline", json_body=query(params)
    )


async def retry_pipeline(params: PipelineParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{_pipeline_path(params)}/retry")


async def cancel_pipeline(params: PipelineParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{_pipeline_path(params)}/cancel")


async def delete_pipeline(params: PipelineParams, ctx: ActionContext) -> Any:
    try:
        await ctx.gitlab.delete(_pipeline_path(params))
    except GitLabForbiddenError as exc:
        hint = "Deleting a pipeline needs the Owner role on the project."
        raise with_hint(exc, hint) from exc
    return {"deleted": params.pipeline_id}


def _pipeline_path(params: PipelineParams) -> str:
    return f"{project_path(params.project)}/pipelines/{params.pipeline_id}"


PIPELINES_TOOL = Tool(
    name="gitlab_pipelines",
    title="GitLab CI/CD pipelines",
    description=(
        "List, inspect, run, retry, cancel, and delete CI/CD pipelines. Statuses are GitLab's "
        "own values. Jobs and their logs are in gitlab_jobs."
    ),
    actions=(
        Action(
            "list",
            "List a project's pipelines, newest first.",
            ListPipelinesParams,
            list_pipelines,
            Access.READ,
        ),
        Action("get", "Get one pipeline.", PipelineParams, get_pipeline, Access.READ),
        Action(
            "create",
            "Run a new pipeline on a branch or tag, optionally with variables.",
            CreatePipelineParams,
            create_pipeline,
            Access.WRITE,
        ),
        Action(
            "retry",
            "Retry a pipeline's failed or canceled jobs.",
            PipelineParams,
            retry_pipeline,
            Access.WRITE,
        ),
        Action(
            "cancel",
            "Cancel a pipeline's running jobs.",
            PipelineParams,
            cancel_pipeline,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete a pipeline with its jobs, logs, and artifacts; this cannot be undone.",
            PipelineParams,
            delete_pipeline,
            Access.WRITE,
            destructive=True,
        ),
    ),
)
