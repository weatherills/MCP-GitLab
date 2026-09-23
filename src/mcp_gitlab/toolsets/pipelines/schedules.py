"""gitlab_pipeline_schedules: pipelines that run on a cron schedule (PRD-05 section 3).

A schedule's variables can hold secrets, so their values are hidden as CI/CD variables' are:
every response leaves them out unless get is called with reveal_values=true, and they are
never logged.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query
from mcp_gitlab.toolsets.pipelines.variables import VariableKey, VariableType, hide_value

ScheduleId = Annotated[
    int, Field(ge=1, description="The pipeline schedule's ID, from list or create.")
]
Cron = Annotated[
    str,
    Field(
        min_length=1,
        description="When to run, as a cron expression, such as 0 2 * * 1-5 for 02:00 on weekdays.",
    ),
]
CronTimezone = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="The time zone the cron expression is in, such as UTC (GitLab's default) or "
        "America/New_York.",
    ),
]
Active = Annotated[
    bool | None,
    Field(
        default=None,
        description="false stops the schedule running without deleting it. New schedules are "
        "active unless this says otherwise.",
    ),
]
ScheduleDescription = Annotated[
    str | None, Field(default=None, min_length=1, description="What the schedule is for.")
]
ScheduleRef = Annotated[
    str | None, Field(default=None, min_length=1, description="Branch or tag to run on.")
]
VARIABLE_VALUE_HELP = "The value. It is stored in GitLab, never echoed back or logged here."


class ListSchedulesParams(PageParams):
    project: ProjectRef
    scope: Literal["active", "inactive"] | None = Field(
        default=None, description="Only active or only inactive schedules; both if omitted."
    )


class ScheduleParams(ActionParams):
    project: ProjectRef
    pipeline_schedule_id: ScheduleId


class GetScheduleParams(ScheduleParams):
    reveal_values: bool = Field(
        default=False,
        description="Include the values of the schedule's variables, which can be secrets. "
        "Leave false unless you truly need them.",
    )


class ListSchedulePipelinesParams(ScheduleParams, PageParams):
    pass


class CreateScheduleParams(ActionParams):
    project: ProjectRef
    description: str = Field(min_length=1, description="What the schedule is for.")
    ref: str = Field(min_length=1, description="Branch or tag to run on.")
    cron: Cron
    cron_timezone: CronTimezone
    active: Active


class UpdateScheduleParams(ScheduleParams):
    description: ScheduleDescription
    ref: ScheduleRef
    cron: Cron | None = None
    cron_timezone: CronTimezone
    active: Active

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateScheduleParams":
        if not query(self, "pipeline_schedule_id"):
            raise ValueError(
                "Nothing to update: set description, ref, cron, cron_timezone, or active."
            )
        return self


class ScheduleVariableParams(ScheduleParams):
    key: VariableKey


class CreateScheduleVariableParams(ScheduleVariableParams):
    value: str = Field(description=VARIABLE_VALUE_HELP)
    variable_type: VariableType


class UpdateScheduleVariableParams(ScheduleVariableParams):
    value: str | None = Field(default=None, description=VARIABLE_VALUE_HELP)
    variable_type: VariableType

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateScheduleVariableParams":
        if not query(self, "pipeline_schedule_id", "key"):
            raise ValueError("Nothing to update: set value or variable_type.")
        return self


async def list_schedules(params: ListSchedulesParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(_schedules_path(params.project), params=query(params))
    return Page(items=[hide_values(schedule) for schedule in page.items], info=page.info)


async def get_schedule(params: GetScheduleParams, ctx: ActionContext) -> Any:
    schedule = await ctx.gitlab.get(_schedule_path(params))
    return schedule if params.reveal_values else hide_values(schedule)


async def list_schedule_pipelines(params: ListSchedulePipelinesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{_schedule_path(params)}/pipelines", params=params.page_query()
    )


async def create_schedule(params: CreateScheduleParams, ctx: ActionContext) -> Any:
    created = await ctx.gitlab.post(_schedules_path(params.project), json_body=query(params))
    return hide_values(created)


async def update_schedule(params: UpdateScheduleParams, ctx: ActionContext) -> Any:
    updated = await ctx.gitlab.put(
        _schedule_path(params), json_body=query(params, "pipeline_schedule_id")
    )
    return hide_values(updated)


async def take_ownership(params: ScheduleParams, ctx: ActionContext) -> Any:
    schedule = await ctx.gitlab.post(f"{_schedule_path(params)}/take_ownership")
    return hide_values(schedule)


async def play_schedule(params: ScheduleParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.post(f"{_schedule_path(params)}/play")
    return {
        "played": params.pipeline_schedule_id,
        "note": "GitLab starts the pipeline shortly; list_pipelines shows it once it exists.",
    }


async def delete_schedule(params: ScheduleParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_schedule_path(params))
    return {"deleted": params.pipeline_schedule_id}


async def create_schedule_variable(params: CreateScheduleVariableParams, ctx: ActionContext) -> Any:
    created = await ctx.gitlab.post(
        f"{_schedule_path(params)}/variables", json_body=query(params, "pipeline_schedule_id")
    )
    return hide_value(created)


async def update_schedule_variable(params: UpdateScheduleVariableParams, ctx: ActionContext) -> Any:
    updated = await ctx.gitlab.put(
        _variable_path(params), json_body=query(params, "pipeline_schedule_id", "key")
    )
    return hide_value(updated)


async def delete_schedule_variable(params: ScheduleVariableParams, ctx: ActionContext) -> Any:
    # GitLab answers with the deleted variable, value included; none of it is passed on.
    await ctx.gitlab.delete(_variable_path(params))
    return {"deleted": params.key}


def hide_values(schedule: Any) -> Any:
    """The schedule with its variables' values left out."""
    if not isinstance(schedule, dict) or not isinstance(schedule.get("variables"), list):
        return schedule
    return {**schedule, "variables": [hide_value(variable) for variable in schedule["variables"]]}


def _schedules_path(project: int | str) -> str:
    return f"{project_path(project)}/pipeline_schedules"


def _schedule_path(params: ScheduleParams) -> str:
    return f"{_schedules_path(params.project)}/{params.pipeline_schedule_id}"


def _variable_path(params: ScheduleVariableParams) -> str:
    return f"{_schedule_path(params)}/variables/{encode_segment(params.key)}"


PIPELINE_SCHEDULES_TOOL = Tool(
    name="gitlab_pipeline_schedules",
    title="GitLab pipeline schedules",
    description=(
        "Run pipelines on a cron schedule: list, create, change, run now, take over, and delete "
        "schedules, and manage their variables. Variable values are hidden except in get with "
        "reveal_values=true."
    ),
    actions=(
        Action(
            "list",
            "List the project's schedules.",
            ListSchedulesParams,
            list_schedules,
            Access.READ,
        ),
        Action(
            "get",
            "Get one schedule with its last pipeline and its variables; their values only with "
            "reveal_values=true.",
            GetScheduleParams,
            get_schedule,
            Access.READ,
        ),
        Action(
            "list_pipelines",
            "List the pipelines a schedule has started, oldest first.",
            ListSchedulePipelinesParams,
            list_schedule_pipelines,
            Access.READ,
        ),
        Action(
            "create",
            "Create a schedule. Its pipelines run as the schedule's owner: you.",
            CreateScheduleParams,
            create_schedule,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a schedule's description, branch, timing, or whether it is active.",
            UpdateScheduleParams,
            update_schedule,
            Access.WRITE,
        ),
        Action(
            "take_ownership",
            "Become the schedule's owner, so its pipelines run with your permissions.",
            ScheduleParams,
            take_ownership,
            Access.WRITE,
        ),
        Action(
            "play",
            "Run the schedule's pipeline now, as the schedule's owner.",
            ScheduleParams,
            play_schedule,
            Access.WRITE,
        ),
        Action("delete", "Delete a schedule.", ScheduleParams, delete_schedule, Access.WRITE),
        Action(
            "create_variable",
            "Add a variable that the schedule's pipelines get.",
            CreateScheduleVariableParams,
            create_schedule_variable,
            Access.WRITE,
        ),
        Action(
            "update_variable",
            "Change a schedule variable's value or type.",
            UpdateScheduleVariableParams,
            update_schedule_variable,
            Access.WRITE,
        ),
        Action(
            "delete_variable",
            "Remove a variable from the schedule.",
            ScheduleVariableParams,
            delete_schedule_variable,
            Access.WRITE,
        ),
    ),
)
