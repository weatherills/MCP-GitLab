"""gitlab_runners: the CI/CD runners a caller can see and manage (PRD-05 section 3).

Registering a runner and resetting a runner or registration token are left out: GitLab answers
each with a token, a secret that would pass through the model.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, group_path, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import GroupRef, ProjectRef, query
from mcp_gitlab.toolsets.pipelines.jobs import JobStatus

RunnerId = Annotated[int, Field(ge=1, description="The runner's ID, from list.")]
PROJECT_HELP = (
    "Project ID, or its full path such as group/subgroup/project. For list, the runners the "
    "project can use, instance runners included; for assign and unassign, the project to add the "
    "runner to or remove it from."
)
Paused = Annotated[
    bool | None,
    Field(
        default=None,
        description="Paused runners take no new jobs. list: only paused (true) or only unpaused "
        "(false) runners; update: pause (true) or resume (false) the runner.",
    ),
]
TagList = Annotated[
    list[Annotated[str, Field(min_length=1)]] | None,
    Field(
        default=None,
        description="Runner tags. list: only runners with all of them; update: replaces the "
        "runner's tags.",
    ),
]
RunnerDescription = Annotated[
    str | None, Field(default=None, description="The runner's description.")
]


class ListRunnersParams(PageParams):
    project: ProjectRef | None = Field(default=None, description=PROJECT_HELP)
    group: GroupRef | None = Field(
        default=None, description="Group ID or full path: list the group's runners."
    )
    type: Literal["instance_type", "group_type", "project_type"] | None = Field(
        default=None, description="Only runners of this type."
    )
    status: Literal["online", "offline", "stale", "never_contacted"] | None = Field(
        default=None, description="Only runners in this state."
    )
    paused: Paused
    tag_list: TagList

    @model_validator(mode="after")
    def _one_scope(self) -> "ListRunnersParams":
        if self.project is not None and self.group is not None:
            raise ValueError("Give project or group, or neither for your own runners.")
        return self


class RunnerParams(ActionParams):
    runner_id: RunnerId


class GetRunnerParams(RunnerParams):
    include_projects: bool | None = Field(
        default=None,
        description="false leaves out the projects the runner serves, which can be a long list.",
    )


class UpdateRunnerParams(RunnerParams):
    description: RunnerDescription
    paused: Paused
    tag_list: TagList
    run_untagged: bool | None = Field(default=None, description="Also take jobs with no tags.")
    locked: bool | None = Field(
        default=None, description="Lock a project runner to the projects it serves now."
    )
    access_level: Literal["not_protected", "ref_protected"] | None = Field(
        default=None,
        description="ref_protected runs only jobs for protected branches and tags.",
    )
    maximum_timeout: int | None = Field(
        default=None, ge=1, description="The longest a job may run on this runner, in seconds."
    )
    maintenance_note: str | None = Field(
        default=None, description="A note for the runner's maintainers."
    )

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateRunnerParams":
        if not query(self, "runner_id"):
            raise ValueError("Nothing to update: set at least one runner setting.")
        return self


class ListRunnerJobsParams(RunnerParams, PageParams):
    job_status: JobStatus | None = Field(default=None, description="Only jobs in this state.")
    sort: Literal["asc", "desc"] | None = Field(
        default=None, description="By job ID: desc (GitLab's default, newest first) or asc."
    )


class AssignRunnerParams(ActionParams):
    project: ProjectRef = Field(description=PROJECT_HELP)
    runner_id: RunnerId


async def list_runners(params: ListRunnersParams, ctx: ActionContext) -> Page:
    if params.project is not None:
        path = f"{project_path(params.project)}/runners"
    elif params.group is not None:
        path = f"{group_path(params.group)}/runners"
    else:
        path = "/runners"
    filters = query(params, "group", "tag_list")
    if params.tag_list:
        filters["tag_list"] = ",".join(params.tag_list)
    return await ctx.gitlab.get_page(path, params=filters)


async def get_runner(params: GetRunnerParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_runner_path(params), params=query(params, "runner_id"))


async def update_runner(params: UpdateRunnerParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(_runner_path(params), json_body=query(params, "runner_id"))


async def delete_runner(params: RunnerParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_runner_path(params))
    return {"deleted": params.runner_id}


async def list_runner_jobs(params: ListRunnerJobsParams, ctx: ActionContext) -> Page:
    filters = query(params, "runner_id", "job_status")
    if params.job_status:
        filters["status"] = params.job_status
    return await ctx.gitlab.get_page(f"{_runner_path(params)}/jobs", params=filters)


async def assign_runner(params: AssignRunnerParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/runners", json_body={"runner_id": params.runner_id}
    )


async def unassign_runner(params: AssignRunnerParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(f"{project_path(params.project)}/runners/{params.runner_id}")
    return {"unassigned": params.runner_id, "project": params.project}


def _runner_path(params: RunnerParams) -> str:
    return f"/runners/{params.runner_id}"


RUNNERS_TOOL = Tool(
    name="gitlab_runners",
    title="GitLab runners",
    description=(
        "See and manage the CI/CD runners that run jobs: list them, pause or retag them, assign "
        "project runners to projects, and see the jobs they ran. Registering runners is left "
        "out, since it hands back a secret token."
    ),
    actions=(
        Action(
            "list",
            "List runners: a project's (instance runners included), a group's, or with neither, "
            "the runners you can manage.",
            ListRunnersParams,
            list_runners,
            Access.READ,
        ),
        Action(
            "get",
            "Get one runner's details: tags, version, when it last contacted GitLab, and its "
            "projects.",
            GetRunnerParams,
            get_runner,
            Access.READ,
        ),
        Action(
            "update",
            "Change a runner's description, tags, or settings, or pause or resume it.",
            UpdateRunnerParams,
            update_runner,
            Access.WRITE,
        ),
        Action(
            "list_jobs",
            "List the jobs a runner is running or has run, in projects you can see.",
            ListRunnerJobsParams,
            list_runner_jobs,
            Access.READ,
        ),
        Action(
            "assign",
            "Let a project use one of your project runners.",
            AssignRunnerParams,
            assign_runner,
            Access.WRITE,
        ),
        Action(
            "unassign",
            "Stop a project using a project runner; the runner stays registered.",
            AssignRunnerParams,
            unassign_runner,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete (unregister) a runner. It takes no more jobs, and bringing it back means "
            "registering it again on its machine.",
            RunnerParams,
            delete_runner,
            Access.WRITE,
            destructive=True,
        ),
    ),
)
