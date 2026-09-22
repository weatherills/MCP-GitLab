"""gitlab_branches: branches and branch protection (PRD-01 section 3)."""

from typing import Annotated, Any

from pydantic import Field

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ACCESS_LEVELS, ProjectRef, ProtectedAccess, Ref, query

BranchName = Annotated[
    str,
    Field(
        min_length=1,
        description="Branch name; protect and unprotect also accept wildcards such as release/*.",
    ),
]


class ListBranchesParams(PageParams):
    project: ProjectRef
    search: str | None = Field(
        default=None, description="Name filter; '^term' anchors the start, 'term$' the end."
    )


class ProjectParams(ActionParams):
    project: ProjectRef


class BranchParams(ActionParams):
    project: ProjectRef
    branch: BranchName


class CreateBranchParams(BranchParams):
    ref: Ref


class ProtectBranchParams(BranchParams):
    push_access_level: ProtectedAccess | None = Field(
        default=None, description="Who may push; GitLab defaults to maintainer."
    )
    merge_access_level: ProtectedAccess | None = Field(
        default=None, description="Who may merge; GitLab defaults to maintainer."
    )
    allow_force_push: bool | None = Field(
        default=None, description="Let members who can push also force-push."
    )


async def list_branches(params: ListBranchesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/repository/branches", params=query(params)
    )


async def get_branch(params: BranchParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_branch_path(params))


async def create_branch(params: CreateBranchParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/repository/branches",
        json_body={"branch": params.branch, "ref": params.ref},
    )


async def delete_branch(params: BranchParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_branch_path(params))
    return {"deleted": params.branch}


async def delete_merged_branches(params: ProjectParams, ctx: ActionContext) -> Any:
    response = await ctx.gitlab.delete(f"{project_path(params.project)}/repository/merged_branches")
    return {
        "status": "deletion_requested",
        "gitlab_response": response,
        "note": "GitLab removes merged branches asynchronously; protected and default branches "
        "are kept.",
    }


async def protect_branch(params: ProtectBranchParams, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {"name": params.branch}
    for field in ("push_access_level", "merge_access_level"):
        level = getattr(params, field)
        if level is not None:
            body[field] = ACCESS_LEVELS[level]
    if params.allow_force_push is not None:
        body["allow_force_push"] = params.allow_force_push
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/protected_branches", json_body=body
    )


async def unprotect_branch(params: BranchParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(
        f"{project_path(params.project)}/protected_branches/{encode_segment(params.branch)}"
    )
    return {"unprotected": params.branch}


async def list_protected_branches(params: ListBranchesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/protected_branches", params=query(params)
    )


def _branch_path(params: BranchParams) -> str:
    return f"{project_path(params.project)}/repository/branches/{encode_segment(params.branch)}"


BRANCHES_TOOL = Tool(
    name="gitlab_branches",
    title="GitLab branches",
    description="List, create, delete, and protect a project's branches.",
    actions=(
        Action("list", "List branches.", ListBranchesParams, list_branches, Access.READ),
        Action(
            "get",
            "Get one branch, including its latest commit.",
            BranchParams,
            get_branch,
            Access.READ,
        ),
        Action(
            "create",
            "Create a branch from a branch, tag, or commit.",
            CreateBranchParams,
            create_branch,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete a branch (not the default or a protected branch).",
            BranchParams,
            delete_branch,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "delete_merged",
            "Delete every branch already merged into the default branch.",
            ProjectParams,
            delete_merged_branches,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "protect",
            "Protect a branch or wildcard.",
            ProtectBranchParams,
            protect_branch,
            Access.WRITE,
        ),
        Action(
            "unprotect",
            "Remove a branch's protection.",
            BranchParams,
            unprotect_branch,
            Access.WRITE,
        ),
        Action(
            "list_protected",
            "List protected branches.",
            ListBranchesParams,
            list_protected_branches,
            Access.READ,
        ),
    ),
)
