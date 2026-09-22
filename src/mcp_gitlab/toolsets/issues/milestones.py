"""gitlab_milestones: a project's milestones and the issues in them (PRD-04 section 3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import IsoDate, ProjectRef, query

MilestoneId = Annotated[
    int, Field(ge=1, description="The milestone's ID (not its IID), from list or get.")
]


class ListMilestonesParams(PageParams):
    project: ProjectRef
    state: Literal["active", "closed"] | None = Field(
        default=None, description="Only active or only closed milestones; both if omitted."
    )
    search: str | None = Field(default=None, description="Match the title or description.")


class MilestoneParams(ActionParams):
    project: ProjectRef
    milestone_id: MilestoneId


class ListMilestoneIssuesParams(MilestoneParams, PageParams):
    pass


class CreateMilestoneParams(ActionParams):
    project: ProjectRef
    title: str = Field(min_length=1, description="Milestone title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    due_date: IsoDate | None = Field(default=None, description="Due date, as YYYY-MM-DD.")
    start_date: IsoDate | None = Field(default=None, description="Start date, as YYYY-MM-DD.")


class UpdateMilestoneParams(MilestoneParams):
    title: str | None = Field(default=None, min_length=1, description="Milestone title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    due_date: IsoDate | None = Field(default=None, description="Due date, as YYYY-MM-DD.")
    start_date: IsoDate | None = Field(default=None, description="Start date, as YYYY-MM-DD.")
    state_event: Literal["close", "activate"] | None = Field(
        default=None, description="close the milestone, or activate (reopen) it."
    )

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateMilestoneParams":
        if not query(self, "milestone_id"):
            raise ValueError("Nothing to update: set at least one field.")
        return self


async def list_milestones(params: ListMilestonesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/milestones", params=query(params)
    )


async def get_milestone(params: MilestoneParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_milestone_path(params))


async def create_milestone(params: CreateMilestoneParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/milestones", json_body=query(params)
    )


async def update_milestone(params: UpdateMilestoneParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(_milestone_path(params), json_body=query(params, "milestone_id"))


async def delete_milestone(params: MilestoneParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_milestone_path(params))
    return {"deleted": params.milestone_id}


async def list_milestone_issues(params: ListMilestoneIssuesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{_milestone_path(params)}/issues", params=params.page_query()
    )


def _milestone_path(params: MilestoneParams) -> str:
    return f"{project_path(params.project)}/milestones/{params.milestone_id}"


MILESTONES_TOOL = Tool(
    name="gitlab_milestones",
    title="GitLab milestones",
    description="List, create, update, close, and delete a project's milestones, and list "
    "their issues.",
    actions=(
        Action("list", "List milestones.", ListMilestonesParams, list_milestones, Access.READ),
        Action("get", "Get one milestone.", MilestoneParams, get_milestone, Access.READ),
        Action(
            "create", "Create a milestone.", CreateMilestoneParams, create_milestone, Access.WRITE
        ),
        Action(
            "update",
            "Change a milestone, or close or reopen it with state_event.",
            UpdateMilestoneParams,
            update_milestone,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete a milestone; its issues and merge requests are kept but unassigned.",
            MilestoneParams,
            delete_milestone,
            Access.WRITE,
        ),
        Action(
            "list_issues",
            "List the issues assigned to a milestone.",
            ListMilestoneIssuesParams,
            list_milestone_issues,
            Access.READ,
        ),
    ),
)
