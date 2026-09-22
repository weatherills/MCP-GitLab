"""gitlab_commits: history, diffs, atomic multi-file commits, cherry-pick, revert (PRD-02 s.3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, Ref, query
from mcp_gitlab.toolsets.diffs import summarize_commit, summarize_diffs

Sha = Annotated[str, Field(min_length=1, description="Commit SHA, or a branch or tag name.")]
TargetBranch = Annotated[str, Field(min_length=1, description="Branch to commit to.")]
IncludeDiffFor = Annotated[
    list[str],
    Field(
        default_factory=list,
        description="File paths whose full diff text to include; every file is summarized.",
    ),
]


class ListCommitsParams(PageParams):
    project: ProjectRef
    ref_name: str | None = Field(
        default=None, min_length=1, description="Branch, tag, or range; default branch if omitted."
    )
    since: str | None = Field(default=None, description="Only commits on or after (ISO 8601).")
    until: str | None = Field(default=None, description="Only commits on or before (ISO 8601).")
    path: str | None = Field(
        default=None, min_length=1, description="Only commits touching this path."
    )
    author: str | None = Field(default=None, description="Only commits by this author.")


class CommitParams(ActionParams):
    project: ProjectRef
    sha: Sha


class DiffParams(PageParams):
    project: ProjectRef
    sha: Sha
    include_diff_for: IncludeDiffFor


class CompareParams(ActionParams):
    project: ProjectRef
    from_ref: Ref
    to_ref: Ref
    straight: bool = Field(
        default=False, description="Compare from..to directly instead of from their merge base."
    )
    include_diff_for: IncludeDiffFor


class CommitAction(ActionParams):
    action: Literal["create", "update", "delete", "move", "chmod"]
    file_path: str = Field(min_length=1, description="Path of the file this action applies to.")
    previous_path: str | None = Field(default=None, description="Original path, for move.")
    content: str | None = Field(default=None, description="New content, for create and update.")
    encoding: Literal["text", "base64"] = Field(default="text", description="Encoding of content.")
    last_commit_id: str | None = Field(
        default=None, description="Rejects update, move, or delete if the file changed since."
    )
    execute_filemode: bool | None = Field(default=None, description="Executable bit, for chmod.")

    @model_validator(mode="after")
    def _complete(self) -> "CommitAction":
        if self.action in ("create", "update") and self.content is None:
            raise ValueError(f"'{self.action}' needs content.")
        if self.action == "move" and not self.previous_path:
            raise ValueError("'move' needs previous_path.")
        if self.action == "chmod" and self.execute_filemode is None:
            raise ValueError("'chmod' needs execute_filemode.")
        return self


class BatchCommitParams(ActionParams):
    project: ProjectRef
    branch: TargetBranch
    commit_message: str = Field(min_length=1, description="Commit message.")
    actions: list[CommitAction] = Field(
        min_length=1, description="File changes, applied atomically."
    )
    start_branch: str | None = Field(
        default=None, min_length=1, description="Existing branch to create a new branch from."
    )
    author_email: str | None = Field(default=None, description="Commit author email.")
    author_name: str | None = Field(default=None, description="Commit author name.")


class CherryPickParams(CommitParams):
    branch: TargetBranch
    dry_run: bool = Field(default=False, description="Check for conflicts without committing.")
    message: str | None = Field(default=None, description="Custom commit message.")


class RevertParams(CommitParams):
    branch: TargetBranch
    dry_run: bool = Field(default=False, description="Check for conflicts without committing.")


class ListStatusesParams(PageParams):
    project: ProjectRef
    sha: Sha
    ref: str | None = Field(
        default=None, min_length=1, description="Branch or tag the statuses ran on."
    )


class ListCommentsParams(PageParams):
    project: ProjectRef
    sha: Sha


class CreateCommentParams(CommitParams):
    note: str = Field(min_length=1, description="Comment text.")
    file_path: str | None = Field(
        default=None, min_length=1, description="File the comment refers to; use with line."
    )
    line: int | None = Field(default=None, ge=1, description="Line the comment refers to.")
    line_type: Literal["new", "old"] | None = Field(
        default=None, description="Whether line counts in the new or old version of the file."
    )


async def list_commits(params: ListCommitsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(_commits_path(params.project), params=query(params))


async def get_commit(params: CommitParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_commit_path(params.project, params.sha))


async def get_diff(params: DiffParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(
        f"{_commit_path(params.project, params.sha)}/diff", params=params.page_query()
    )
    return Page(items=summarize_diffs(page.items, params.include_diff_for), info=page.info)


async def compare(params: CompareParams, ctx: ActionContext) -> Any:
    result = await ctx.gitlab.get(
        f"{project_path(params.project)}/repository/compare",
        params={"from": params.from_ref, "to": params.to_ref, "straight": params.straight},
    )
    return {
        "commits": [summarize_commit(commit) for commit in result.get("commits") or []],
        "diffs": summarize_diffs(result.get("diffs") or [], params.include_diff_for),
        "compare_timeout": result.get("compare_timeout"),
        "compare_same_ref": result.get("compare_same_ref"),
    }


async def batch_commit(params: BatchCommitParams, ctx: ActionContext) -> Any:
    body = query(params, "actions")
    body["actions"] = [action.model_dump(exclude_none=True) for action in params.actions]
    return await ctx.gitlab.post(_commits_path(params.project), json_body=body)


async def cherry_pick(params: CherryPickParams, ctx: ActionContext) -> Any:
    body = query(params, "sha")
    return await ctx.gitlab.post(
        f"{_commit_path(params.project, params.sha)}/cherry_pick", json_body=body
    )


async def revert(params: RevertParams, ctx: ActionContext) -> Any:
    body = query(params, "sha")
    return await ctx.gitlab.post(
        f"{_commit_path(params.project, params.sha)}/revert", json_body=body
    )


async def list_statuses(params: ListStatusesParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{_commit_path(params.project, params.sha)}/statuses", params=query(params, "sha")
    )


async def list_comments(params: ListCommentsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{_commit_path(params.project, params.sha)}/comments", params=params.page_query()
    )


async def create_comment(params: CreateCommentParams, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {"note": params.note}
    if params.file_path is not None:
        body["path"] = params.file_path
    if params.line is not None:
        body["line"] = params.line
    if params.line_type is not None:
        body["line_type"] = params.line_type
    return await ctx.gitlab.post(
        f"{_commit_path(params.project, params.sha)}/comments", json_body=body
    )


def _commits_path(project: int | str) -> str:
    return f"{project_path(project)}/repository/commits"


def _commit_path(project: int | str, sha: str) -> str:
    return f"{_commits_path(project)}/{encode_segment(sha)}"


COMMITS_TOOL = Tool(
    name="gitlab_commits",
    title="GitLab commits",
    description=(
        "Inspect history and diffs, and commit changes: batch_commit applies several file changes "
        "as one atomic commit."
    ),
    actions=(
        Action("list", "List commits.", ListCommitsParams, list_commits, Access.READ),
        Action("get", "Get one commit.", CommitParams, get_commit, Access.READ),
        Action(
            "get_diff",
            "Summarize a commit's changed files; full diff text for include_diff_for paths.",
            DiffParams,
            get_diff,
            Access.READ,
        ),
        Action(
            "compare",
            "Compare two branches, tags, or commits.",
            CompareParams,
            compare,
            Access.READ,
        ),
        Action(
            "batch_commit",
            "Create, update, delete, move, or chmod several files in one atomic commit.",
            BatchCommitParams,
            batch_commit,
            Access.WRITE,
        ),
        Action(
            "cherry_pick",
            "Cherry-pick a commit onto a branch.",
            CherryPickParams,
            cherry_pick,
            Access.WRITE,
        ),
        Action("revert", "Revert a commit on a branch.", RevertParams, revert, Access.WRITE),
        Action(
            "list_statuses",
            "List a commit's CI statuses.",
            ListStatusesParams,
            list_statuses,
            Access.READ,
        ),
        Action(
            "list_comments",
            "List comments on a commit.",
            ListCommentsParams,
            list_comments,
            Access.READ,
        ),
        Action(
            "create_comment",
            "Comment on a commit.",
            CreateCommentParams,
            create_comment,
            Access.WRITE,
        ),
    ),
)
