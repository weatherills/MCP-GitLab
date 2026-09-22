"""gitlab_release_links: asset links attached to a release (PRD-06 section 3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets.common import query
from mcp_gitlab.toolsets.releases.releases import ReleaseParams, release_path

LinkId = Annotated[int, Field(ge=1, description="The link's ID, from list.")]
LinkType = Annotated[
    Literal["other", "runbook", "image", "package"] | None,
    Field(default=None, description="other (the default), runbook, image, or package."),
]
DirectAssetPath = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="Permanent path for the asset under the release, such as /binaries/app.",
    ),
]


class ListLinksParams(ReleaseParams, PageParams):
    pass


class LinkParams(ReleaseParams):
    link_id: LinkId


class CreateLinkParams(ReleaseParams):
    name: str = Field(min_length=1, description="Link name, unique within the release.")
    url: str = Field(min_length=1, description="URL of the asset, unique within the release.")
    direct_asset_path: DirectAssetPath
    link_type: LinkType


class UpdateLinkParams(LinkParams):
    name: str | None = Field(
        default=None, min_length=1, description="Link name, unique within the release."
    )
    url: str | None = Field(
        default=None, min_length=1, description="URL of the asset, unique within the release."
    )
    direct_asset_path: DirectAssetPath
    link_type: LinkType

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateLinkParams":
        if not query(self, "tag", "link_id"):
            raise ValueError("Nothing to update: set name, url, direct_asset_path, or link_type.")
        return self


async def list_links(params: ListLinksParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(_links_path(params), params=params.page_query())


async def get_link(params: LinkParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{_links_path(params)}/{params.link_id}")


async def create_link(params: CreateLinkParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(_links_path(params), json_body=query(params, "tag"))


async def update_link(params: UpdateLinkParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(
        f"{_links_path(params)}/{params.link_id}", json_body=query(params, "tag", "link_id")
    )


async def delete_link(params: LinkParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.delete(f"{_links_path(params)}/{params.link_id}")


def _links_path(params: ReleaseParams) -> str:
    return f"{release_path(params)}/assets/links"


RELEASE_LINKS_TOOL = Tool(
    name="gitlab_release_links",
    title="GitLab release asset links",
    description="List, add, update, and remove the asset links attached to a release.",
    actions=(
        Action("list", "List a release's asset links.", ListLinksParams, list_links, Access.READ),
        Action("get", "Get one asset link.", LinkParams, get_link, Access.READ),
        Action("create", "Add an asset link.", CreateLinkParams, create_link, Access.WRITE),
        Action("update", "Change an asset link.", UpdateLinkParams, update_link, Access.WRITE),
        Action("delete", "Remove an asset link.", LinkParams, delete_link, Access.WRITE),
    ),
)
