"""gitlab_releases: releases, which add notes and assets on top of a tag (PRD-06 section 3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query

TagName = Annotated[str, Field(min_length=1, description="The release's tag, such as v1.2.0.")]
ReleasedAt = Annotated[
    str | None,
    Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}(T[0-9:.]+(Z|[+-]\d{2}:?\d{2})?)?$",
        description="When the release is or was ready, in ISO 8601, such as 2026-10-01T12:00:00Z. "
        "A future date marks it as upcoming.",
    ),
]
Milestones = Annotated[
    list[str] | None,
    Field(default=None, description="Titles of milestones to associate; replaces them on update."),
]


class ListReleasesParams(PageParams):
    project: ProjectRef
    order_by: Literal["released_at", "created_at"] | None = Field(
        default=None, description="Sort field; GitLab defaults to released_at."
    )
    sort: Literal["asc", "desc"] | None = Field(
        default=None, description="Sort direction; GitLab defaults to desc (newest first)."
    )


class ReleaseParams(ActionParams):
    project: ProjectRef
    tag: TagName


class CreateReleaseParams(ReleaseParams):
    name: str | None = Field(default=None, min_length=1, description="Release title.")
    description: str | None = Field(default=None, description="Release notes, in Markdown.")
    ref: str | None = Field(
        default=None,
        min_length=1,
        description="Branch, tag, or commit to create the tag from, when the tag does not exist "
        "yet.",
    )
    tag_message: str | None = Field(
        default=None, description="Message for the tag, when this creates it (annotated tag)."
    )
    released_at: ReleasedAt
    milestones: Milestones


class UpdateReleaseParams(ReleaseParams):
    name: str | None = Field(default=None, min_length=1, description="Release title.")
    description: str | None = Field(default=None, description="Release notes, in Markdown.")
    released_at: ReleasedAt
    milestones: Milestones

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateReleaseParams":
        if not query(self, "tag"):
            raise ValueError(
                "Nothing to update: set name, description, released_at, or milestones."
            )
        return self


async def list_releases(params: ListReleasesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/releases", params=query(params)
    )


async def get_release(params: ReleaseParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(release_path(params))


async def create_release(params: CreateReleaseParams, ctx: ActionContext) -> Any:
    body = {"tag_name": params.tag, **query(params, "tag")}
    return await ctx.gitlab.post(f"{project_path(params.project)}/releases", json_body=body)


async def update_release(params: UpdateReleaseParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(release_path(params), json_body=query(params, "tag"))


async def delete_release(params: ReleaseParams, ctx: ActionContext) -> Any:
    deleted = await ctx.gitlab.delete(release_path(params))
    return {
        "deleted_release": params.tag,
        "tag_kept": True,
        "note": "Only the release was deleted; the tag and its commits remain (delete the tag "
        "with gitlab_tags if needed).",
        "gitlab_response": deleted,
    }


def release_path(params: ReleaseParams) -> str:
    return f"{project_path(params.project)}/releases/{encode_segment(params.tag)}"


RELEASES_TOOL = Tool(
    name="gitlab_releases",
    title="GitLab releases",
    description=(
        "List, create, update, and delete releases: release notes and metadata on top of a tag. "
        "Asset links are in gitlab_release_links."
    ),
    actions=(
        Action(
            "list", "List a project's releases.", ListReleasesParams, list_releases, Access.READ
        ),
        Action("get", "Get the release for a tag.", ReleaseParams, get_release, Access.READ),
        Action(
            "create",
            "Create a release for a tag; give ref to create the tag too if it does not exist.",
            CreateReleaseParams,
            create_release,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a release's title, notes, date, or milestones.",
            UpdateReleaseParams,
            update_release,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete a release. The tag is kept: only the release notes and metadata go.",
            ReleaseParams,
            delete_release,
            Access.WRITE,
        ),
    ),
)
