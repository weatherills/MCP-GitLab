"""gitlab_repository_tree: browse a repository's directories (PRD-02 section 3)."""

from pydantic import Field

from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query


class ListTreeParams(PageParams):
    project: ProjectRef
    path: str | None = Field(
        default=None, min_length=1, description="Directory to list; the repository root if omitted."
    )
    ref: str | None = Field(
        default=None,
        min_length=1,
        description="Branch, tag, or commit; the default branch if omitted.",
    )
    recursive: bool = Field(
        default=False, description="List the whole subtree, not just one level."
    )


async def list_tree(params: ListTreeParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/repository/tree", params=query(params)
    )


TREE_TOOL = Tool(
    name="gitlab_repository_tree",
    title="GitLab repository tree",
    description="List the files and directories in a repository at any branch, tag, or commit.",
    actions=(
        Action("list", "List a directory's entries.", ListTreeParams, list_tree, Access.READ),
    ),
)
