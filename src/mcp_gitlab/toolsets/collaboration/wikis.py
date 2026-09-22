"""gitlab_wikis: a project's wiki pages (PRD-08 section 3).

GitLab returns a wiki's whole page list in one response (the endpoint is not paginated), so
list leaves content out unless asked for it.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query

Slug = Annotated[
    str,
    Field(min_length=1, description="The page's slug, such as home or docs/setup, from list."),
]
Title = Annotated[
    str,
    Field(
        min_length=1,
        description="Page title; the slug is made from it, and a / nests the page, as in "
        "docs/Setup.",
    ),
]
WikiFormat = Annotated[
    Literal["markdown", "rdoc", "asciidoc", "org"] | None,
    Field(
        default=None,
        description="Markup of the page: markdown (the default for a new page), rdoc, asciidoc, "
        "or org. update keeps the page's current format unless this is given.",
    ),
]


class ListWikiPagesParams(ActionParams):
    project: ProjectRef
    with_content: bool = Field(
        default=False, description="Include every page's content; leave false for an index."
    )


class WikiPageParams(ActionParams):
    project: ProjectRef
    slug: Slug


class GetWikiPageParams(WikiPageParams):
    version: str | None = Field(
        default=None, min_length=1, description="Commit SHA of an earlier version of the page."
    )
    render_html: bool | None = Field(
        default=None, description="Return the content rendered as HTML instead of its source."
    )


class CreateWikiPageParams(ActionParams):
    project: ProjectRef
    title: Title
    content: str = Field(description="Page content, in the page's format.")
    format: WikiFormat


class UpdateWikiPageParams(WikiPageParams):
    title: Title | None = Field(
        default=None, description="New title; the page moves to a slug made from it."
    )
    content: str | None = Field(
        default=None, description="New page content, replacing the old; in the page's format."
    )
    format: WikiFormat

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateWikiPageParams":
        if self.title is None and self.content is None and self.format is None:
            raise ValueError("Nothing to update: set title, content, or format.")
        return self


async def list_wiki_pages(params: ListWikiPagesParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_wiki_path(params.project), params=query(params))


async def get_wiki_page(params: GetWikiPageParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_page_path(params), params=query(params, "slug"))


async def create_wiki_page(params: CreateWikiPageParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(_wiki_path(params.project), json_body=query(params))


async def update_wiki_page(params: UpdateWikiPageParams, ctx: ActionContext) -> Any:
    body = query(params, "slug")
    if params.format is None:
        # GitLab converts a page to markdown when an update leaves format out; keep its own.
        current = await ctx.gitlab.get(_page_path(params))
        if isinstance(current, dict) and isinstance(current.get("format"), str):
            body["format"] = current["format"]
    page = await ctx.gitlab.put(_page_path(params), json_body=body)
    if isinstance(page, dict) and page.get("slug") not in (None, params.slug):
        return {**page, "note": f"The new title moved the page: its slug is now {page['slug']}."}
    return page


async def delete_wiki_page(params: WikiPageParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_page_path(params))
    return {"deleted": params.slug}


def _wiki_path(project: int | str) -> str:
    return f"{project_path(project)}/wikis"


def _page_path(params: WikiPageParams) -> str:
    return f"{_wiki_path(params.project)}/{encode_segment(params.slug)}"


WIKIS_TOOL = Tool(
    name="gitlab_wikis",
    title="GitLab project wikis",
    description="List, read, create, edit, and delete the pages of a project's wiki.",
    actions=(
        Action(
            "list",
            "List the wiki's pages (titles and slugs; with_content adds their text).",
            ListWikiPagesParams,
            list_wiki_pages,
            Access.READ,
        ),
        Action(
            "get",
            "Get one page's content, or an earlier version of it.",
            GetWikiPageParams,
            get_wiki_page,
            Access.READ,
        ),
        Action("create", "Create a page.", CreateWikiPageParams, create_wiki_page, Access.WRITE),
        Action(
            "update",
            "Change a page's content, title, or format; a new title moves the page to a new slug.",
            UpdateWikiPageParams,
            update_wiki_page,
            Access.WRITE,
        ),
        Action("delete", "Delete a page.", WikiPageParams, delete_wiki_page, Access.WRITE),
    ),
)
