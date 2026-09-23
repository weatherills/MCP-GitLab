"""gitlab_badges: the badges shown on a project's overview page (PRD-01 section 3)."""

from typing import Annotated, Any

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query

BadgeId = Annotated[int, Field(ge=1, description="The badge's ID, from list.")]
BadgeUrl = Annotated[
    str,
    Field(
        min_length=1,
        description="URL, which may use placeholders such as %{project_path}, %{default_branch}, "
        "and %{commit_sha}.",
    ),
]
BadgeName = Annotated[str | None, Field(default=None, min_length=1, description="Badge name.")]


class ListBadgesParams(PageParams):
    project: ProjectRef
    name: str | None = Field(default=None, min_length=1, description="Only badges with this name.")


class BadgeParams(ActionParams):
    project: ProjectRef
    badge_id: BadgeId


class CreateBadgeParams(ActionParams):
    project: ProjectRef
    link_url: BadgeUrl
    image_url: BadgeUrl
    name: BadgeName


class UpdateBadgeParams(BadgeParams):
    link_url: BadgeUrl | None = None
    image_url: BadgeUrl | None = None
    name: BadgeName

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateBadgeParams":
        if not query(self, "badge_id"):
            raise ValueError("Nothing to update: set link_url, image_url, or name.")
        return self


class PreviewBadgeParams(ActionParams):
    project: ProjectRef
    link_url: BadgeUrl
    image_url: BadgeUrl


async def list_badges(params: ListBadgesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(_badges_path(params.project), params=query(params))


async def get_badge(params: BadgeParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_badge_path(params))


async def create_badge(params: CreateBadgeParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(_badges_path(params.project), json_body=query(params))


async def update_badge(params: UpdateBadgeParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(_badge_path(params), json_body=query(params, "badge_id"))


async def delete_badge(params: BadgeParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_badge_path(params))
    return {"deleted": params.badge_id}


async def preview_badge(params: PreviewBadgeParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{_badges_path(params.project)}/render", params=query(params))


def _badges_path(project: int | str) -> str:
    return f"{project_path(project)}/badges"


def _badge_path(params: BadgeParams) -> str:
    return f"{_badges_path(params.project)}/{params.badge_id}"


BADGES_TOOL = Tool(
    name="gitlab_badges",
    title="GitLab project badges",
    description="List, add, change, and remove the badges on a project's overview page, such as a "
    "pipeline status or coverage badge.",
    actions=(
        Action(
            "list",
            "List the project's badges, including its group's (kind says which).",
            ListBadgesParams,
            list_badges,
            Access.READ,
        ),
        Action("get", "Get one badge.", BadgeParams, get_badge, Access.READ),
        Action("create", "Add a badge.", CreateBadgeParams, create_badge, Access.WRITE),
        Action(
            "update",
            "Change a project badge's link, image, or name; group badges belong to the group.",
            UpdateBadgeParams,
            update_badge,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Remove a project badge; group badges belong to the group.",
            BadgeParams,
            delete_badge,
            Access.WRITE,
        ),
        Action(
            "preview",
            "Show the link and image URLs a badge would have, with its placeholders filled in.",
            PreviewBadgeParams,
            preview_badge,
            Access.READ,
        ),
    ),
)
