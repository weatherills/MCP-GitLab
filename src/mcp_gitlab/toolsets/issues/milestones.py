"""gitlab_milestones: a project's or a group's milestones, and the issues and merge requests in
them (PRD-04 section 3)."""

from collections.abc import Awaitable
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabNotFoundError
from mcp_gitlab.gitlab import Page
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets.common import IsoDate, ProjectOrGroup, query, with_hint

MilestoneId = Annotated[
    int, Field(ge=1, description="The milestone's ID (not its IID), from list or get.")
]
INHERITED_HINT = (
    "A milestone the project inherits from a group belongs to that group: give group instead of "
    "project."
)


class ListMilestonesParams(ProjectOrGroup, PageParams):
    state: Literal["active", "closed"] | None = Field(
        default=None, description="Only active or only closed milestones; both if omitted."
    )
    search: str | None = Field(default=None, description="Match the title or description.")
    include_ancestors: bool | None = Field(
        default=None,
        description="Also list the parent groups' milestones, which the project's issues can use "
        "too (GitLab 16.7 and later). Without it, a project's list has only its own.",
    )


class MilestoneParams(ProjectOrGroup):
    milestone_id: MilestoneId


class ListMilestoneItemsParams(MilestoneParams, PageParams):
    pass


class CreateMilestoneParams(ProjectOrGroup):
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
        if not query(self, "group", "milestone_id"):
            raise ValueError("Nothing to update: set at least one field.")
        return self


async def list_milestones(params: ListMilestonesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{params.owner_path()}/milestones", params=query(params, "group")
    )


async def get_milestone(params: MilestoneParams, ctx: ActionContext) -> Any:
    return await _on_milestone(params, ctx.gitlab.get(_milestone_path(params)))


async def create_milestone(params: CreateMilestoneParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{params.owner_path()}/milestones", json_body=query(params, "group")
    )


async def update_milestone(params: UpdateMilestoneParams, ctx: ActionContext) -> Any:
    body = query(params, "group", "milestone_id")
    return await _on_milestone(params, ctx.gitlab.put(_milestone_path(params), json_body=body))


async def delete_milestone(params: MilestoneParams, ctx: ActionContext) -> Any:
    await _on_milestone(params, ctx.gitlab.delete(_milestone_path(params)))
    return {"deleted": params.milestone_id}


async def list_milestone_issues(params: ListMilestoneItemsParams, ctx: ActionContext) -> Page:
    path = f"{_milestone_path(params)}/issues"
    page: Page = await _on_milestone(params, ctx.gitlab.get_page(path, params=params.page_query()))
    return page


async def list_milestone_merge_requests(
    params: ListMilestoneItemsParams, ctx: ActionContext
) -> Page:
    path = f"{_milestone_path(params)}/merge_requests"
    page: Page = await _on_milestone(params, ctx.gitlab.get_page(path, params=params.page_query()))
    return page


async def _on_milestone(params: MilestoneParams, call: Awaitable[Any]) -> Any:
    """Await a call on one milestone, pointing a project's caller at the group on a 404."""
    try:
        return await call
    except GitLabNotFoundError as exc:
        # A project reaches its groups' milestones in lists, but not by ID.
        gitlab_message = str(exc.details.get("gitlab_message", ""))
        if params.project is not None and "Project Not Found" not in gitlab_message:
            raise with_hint(exc, INHERITED_HINT) from exc
        raise


def _milestone_path(params: MilestoneParams) -> str:
    return f"{params.owner_path()}/milestones/{params.milestone_id}"


MILESTONES_TOOL = Tool(
    name="gitlab_milestones",
    title="GitLab milestones",
    description="List, create, update, close, and delete a project's or a group's milestones, "
    "and list their issues and merge requests.",
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
            ListMilestoneItemsParams,
            list_milestone_issues,
            Access.READ,
        ),
        Action(
            "list_merge_requests",
            "List the merge requests assigned to a milestone.",
            ListMilestoneItemsParams,
            list_milestone_merge_requests,
            Access.READ,
        ),
    ),
)
