"""gitlab_tags: tags and tag protection (PRD-01 section 3).

Release notes are not set here: GitLab's Tags API has no such parameter; they
belong to the Releases API (PRD-06).
"""

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ACCESS_LEVELS, ProjectRef, ProtectedAccess, Ref, query

TagName = Annotated[
    str,
    Field(
        min_length=1,
        description="Tag name; protect and unprotect also accept wildcards such as v*.",
    ),
]


class ListTagsParams(PageParams):
    project: ProjectRef
    search: str | None = Field(
        default=None, description="Name filter; '^term' anchors the start, 'term$' the end."
    )
    order_by: Literal["name", "updated", "version"] | None = Field(
        default=None, description="Sort key; 'version' sorts by semantic version."
    )
    sort: Literal["asc", "desc"] | None = Field(default=None, description="Sort direction.")


class TagParams(ActionParams):
    project: ProjectRef
    tag: TagName


class CreateTagParams(TagParams):
    ref: Ref
    message: str | None = Field(default=None, description="Message for an annotated tag.")


class ProtectTagParams(TagParams):
    create_access_level: ProtectedAccess | None = Field(
        default=None, description="Who may create matching tags; GitLab defaults to maintainer."
    )


class ListProtectedTagsParams(PageParams):
    project: ProjectRef


async def list_tags(params: ListTagsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/repository/tags", params=query(params)
    )


async def get_tag(params: TagParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_tag_path(params))


async def create_tag(params: CreateTagParams, ctx: ActionContext) -> Any:
    body = {"tag_name": params.tag, "ref": params.ref}
    if params.message is not None:
        body["message"] = params.message
    return await ctx.gitlab.post(f"{project_path(params.project)}/repository/tags", json_body=body)


async def delete_tag(params: TagParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_tag_path(params))
    return {"deleted": params.tag}


async def protect_tag(params: ProtectTagParams, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {"name": params.tag}
    if params.create_access_level is not None:
        body["create_access_level"] = ACCESS_LEVELS[params.create_access_level]
    return await ctx.gitlab.post(f"{project_path(params.project)}/protected_tags", json_body=body)


async def unprotect_tag(params: TagParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(
        f"{project_path(params.project)}/protected_tags/{encode_segment(params.tag)}"
    )
    return {"unprotected": params.tag}


async def list_protected_tags(params: ListProtectedTagsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/protected_tags", params=query(params)
    )


def _tag_path(params: TagParams) -> str:
    return f"{project_path(params.project)}/repository/tags/{encode_segment(params.tag)}"


TAGS_TOOL = Tool(
    name="gitlab_tags",
    title="GitLab tags",
    description="List, create, delete, and protect a project's tags.",
    actions=(
        Action("list", "List tags.", ListTagsParams, list_tags, Access.READ),
        Action("get", "Get one tag.", TagParams, get_tag, Access.READ),
        Action(
            "create",
            "Create a tag (annotated when a message is given).",
            CreateTagParams,
            create_tag,
            Access.WRITE,
        ),
        Action("delete", "Delete a tag.", TagParams, delete_tag, Access.WRITE),
        Action(
            "protect", "Protect a tag or wildcard.", ProtectTagParams, protect_tag, Access.WRITE
        ),
        Action("unprotect", "Remove a tag's protection.", TagParams, unprotect_tag, Access.WRITE),
        Action(
            "list_protected",
            "List protected tags.",
            ListProtectedTagsParams,
            list_protected_tags,
            Access.READ,
        ),
    ),
)
