"""gitlab_merge_requests: the merge request lifecycle, diffs, merge, and rebase (PRD-03 s.3)."""

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabError, ToolError
from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query, with_csv_labels
from mcp_gitlab.toolsets.diffs import summarize_commit, summarize_diffs
from mcp_gitlab.toolsets.threads import NoteableRef

MergeRequestIid = Annotated[
    int, Field(ge=1, description="The merge request's IID: the number shown as !12 in GitLab.")
]
BranchName = Annotated[str, Field(min_length=1)]
UserId = Annotated[int, Field(ge=1)]
Labels = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Label names. list matches merge requests that have all of them; create and "
        "update set exactly these, replacing any others.",
    ),
]
AssigneeIds = Annotated[
    list[UserId] | None,
    Field(
        default=None,
        description="Assignee user IDs, replacing any others; an empty list unassigns everyone.",
    ),
]
Draft = Annotated[
    bool | None,
    Field(
        default=None,
        description="true marks the merge request as a draft (GitLab's 'Draft:' title prefix); "
        "false marks it ready.",
    ),
]
Squash = Annotated[
    bool | None, Field(default=None, description="Squash the commits into one when merging.")
]

# GitLab treats a merge request as a draft when its title starts with one of these.
_DRAFT_MARKER = re.compile(r"^\s*(?:\[draft\]|\(draft\)|draft:)\s*", re.IGNORECASE)


class MergeRequestRef(NoteableRef):
    collection: ClassVar[str] = "merge_requests"
    iid_field: ClassVar[str] = "merge_request_iid"

    merge_request_iid: MergeRequestIid


class ListMergeRequestsParams(PageParams):
    project: ProjectRef
    state: Literal["opened", "closed", "locked", "merged", "all"] | None = Field(
        default=None,
        description="Only merge requests in this state; GitLab returns all if omitted.",
    )
    source_branch: BranchName | None = Field(default=None, description="Source branch.")
    target_branch: BranchName | None = Field(default=None, description="Target branch.")
    author_id: UserId | None = Field(default=None, description="Author's user ID.")
    assignee_id: UserId | None = Field(default=None, description="Assignee's user ID.")
    labels: Labels
    search: str | None = Field(default=None, description="Match the title or description.")


class GetMergeRequestParams(MergeRequestRef):
    include_diverged_commits_count: bool | None = Field(
        default=None, description="Also report how many commits the target branch is ahead."
    )
    include_rebase_in_progress: bool | None = Field(
        default=None, description="Also report whether a rebase is running (see rebase)."
    )


class CreateMergeRequestParams(ActionParams):
    project: ProjectRef
    source_branch: BranchName = Field(description="Source branch.")
    target_branch: BranchName = Field(description="Target branch.")
    title: str = Field(min_length=1, description="Merge request title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    labels: Labels
    assignee_ids: AssigneeIds
    draft: Draft
    remove_source_branch: bool | None = Field(
        default=None, description="Delete the source branch when the merge request merges."
    )
    squash: Squash
    target_project_id: int | None = Field(
        default=None, ge=1, description="Target project ID, when merging from a fork."
    )


class UpdateMergeRequestParams(MergeRequestRef):
    title: str | None = Field(default=None, min_length=1, description="Merge request title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    labels: Labels
    assignee_ids: AssigneeIds
    target_branch: BranchName | None = Field(default=None, description="Target branch.")
    draft: Draft

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateMergeRequestParams":
        if not self.fields():
            raise ValueError("Nothing to update: set at least one field.")
        return self


class DiffParams(MergeRequestRef, PageParams):
    include_diff_for: list[str] = Field(
        default_factory=list,
        description="File paths whose full diff text to include; every file is summarized.",
    )


class CommitsParams(MergeRequestRef, PageParams):
    pass


class MergeParams(MergeRequestRef):
    squash: Squash
    should_remove_source_branch: bool | None = Field(
        default=None, description="Delete the source branch after merging."
    )
    auto_merge: bool | None = Field(
        default=None,
        description="Merge automatically once the pipeline and other checks pass, instead of now.",
    )
    sha: str | None = Field(
        default=None,
        min_length=1,
        description="Merge only if this is still the source branch's head commit (get's sha).",
    )


class RebaseParams(MergeRequestRef):
    skip_ci: bool | None = Field(
        default=None, description="Don't start a pipeline for the rebased commits."
    )


class MergeBlockedError(ToolError):
    """GitLab refused the merge for a reason the caller has to act on."""

    code = "merge_blocked"


class MergePendingError(ToolError):
    """GitLab refused the merge for now; waiting and retrying can succeed."""

    code = "merge_pending"
    retryable = True


# detailed_merge_status -> (what to do next, whether waiting alone can fix it)
_NEXT_STEPS: dict[str, tuple[str, bool]] = {
    "ci_must_pass": (
        "A pipeline must succeed first: check it with gitlab_pipelines, or merge with "
        "auto_merge=true to merge once it passes.",
        False,
    ),
    "ci_still_running": (
        "The pipeline is still running: wait for it, or merge with auto_merge=true.",
        True,
    ),
    "conflict": (
        "The source branch conflicts with the target branch. Resolve the conflicts on the "
        "source branch; an automatic rebase cannot.",
        False,
    ),
    "need_rebase": ("Rebase the source branch first: call rebase, then merge again.", False),
    "not_approved": ("The merge request needs more approvals before it can merge.", False),
    "requested_changes": ("A reviewer requested changes; address them first.", False),
    "discussions_not_resolved": (
        "Unresolved threads block merging: resolve them with gitlab_mr_reviews resolve_discussion.",
        False,
    ),
    "draft_status": ("It is a draft: mark it ready with update and draft=false.", False),
    "not_open": ("It is not open: it was already merged or closed.", False),
    "merge_request_blocked": ("Another merge request it depends on must merge first.", False),
    "merge_time": ("It cannot merge before its scheduled merge time.", True),
    "commits_status": ("The source branch must exist and contain commits.", False),
    "checking": ("GitLab is still checking mergeability; retry shortly.", True),
    "unchecked": ("GitLab has not checked mergeability yet; retry shortly.", True),
    "preparing": ("GitLab is still preparing the diff; retry shortly.", True),
    "approvals_syncing": ("GitLab is still syncing approvals; retry shortly.", True),
}


async def list_merge_requests(params: ListMergeRequestsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/merge_requests", params=with_csv_labels(query(params))
    )


async def get_merge_request(params: GetMergeRequestParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(params.path(), params=params.fields())


async def create_merge_request(params: CreateMergeRequestParams, ctx: ActionContext) -> Any:
    body = with_csv_labels(query(params, "draft"))
    if params.draft is not None:
        body["title"] = _with_draft_marker(params.title, params.draft)
    return await ctx.gitlab.post(f"{project_path(params.project)}/merge_requests", json_body=body)


async def update_merge_request(params: UpdateMergeRequestParams, ctx: ActionContext) -> Any:
    body = with_csv_labels(params.fields("draft"))
    if params.draft is not None:
        title = params.title or (await ctx.gitlab.get(params.path()))["title"]
        body["title"] = _with_draft_marker(title, params.draft)
    return await ctx.gitlab.put(params.path(), json_body=body)


async def close_merge_request(params: MergeRequestRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(params.path(), json_body={"state_event": "close"})


async def reopen_merge_request(params: MergeRequestRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(params.path(), json_body={"state_event": "reopen"})


async def get_diff(params: DiffParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(f"{params.path()}/diffs", params=params.page_query())
    return Page(items=summarize_diffs(page.items, params.include_diff_for), info=page.info)


async def list_commits(params: CommitsParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(f"{params.path()}/commits", params=params.page_query())
    return Page(items=[summarize_commit(commit) for commit in page.items], info=page.info)


async def merge(params: MergeParams, ctx: ActionContext) -> Any:
    body = params.fields()
    if params.auto_merge:
        # auto_merge replaced merge_when_pipeline_succeeds in GitLab 17.11; send both so older
        # instances also wait instead of merging immediately.
        body["merge_when_pipeline_succeeds"] = True
    try:
        return await ctx.gitlab.put(f"{params.path()}/merge", json_body=body)
    except GitLabError as exc:
        raise await _merge_refusal(params, ctx, exc) from exc


async def rebase(params: RebaseParams, ctx: ActionContext) -> Any:
    response = await ctx.gitlab.put(f"{params.path()}/rebase", json_body=params.fields())
    return {
        **(response if isinstance(response, dict) else {}),
        "note": "GitLab rebases in the background: call get with include_rebase_in_progress=true "
        "until rebase_in_progress is false; merge_error then reports any failure.",
    }


async def _merge_refusal(params: MergeParams, ctx: ActionContext, exc: GitLabError) -> ToolError:
    """Turn GitLab's terse merge refusal into an error that says what to do next."""
    gitlab_message = str(exc.details.get("gitlab_message") or exc.message)
    details: dict[str, Any] = {"gitlab_status": exc.status, "gitlab_message": gitlab_message}
    if exc.status == 409:
        return MergeBlockedError(
            f"The source branch has commits newer than sha {params.sha}: review them, then "
            "merge again with the current sha from get.",
            details=details,
        )
    if exc.status == 400 and "sha" in gitlab_message.lower():
        return MergeBlockedError(
            "This GitLab instance requires sha when merging: pass the merge request's current "
            "sha from get.",
            details=details,
        )
    if exc.status not in (405, 406, 422):
        return exc
    try:
        current = await ctx.gitlab.get(params.path())
    except GitLabError:
        return exc
    status = str(current.get("detailed_merge_status") or current.get("merge_status") or "unknown")
    next_step, waiting_helps = _NEXT_STEPS.get(
        status,
        (
            f"A project rule blocks merging ({status}); a person may need to resolve it.",
            False,
        ),
    )
    details.update(
        detailed_merge_status=status,
        has_conflicts=current.get("has_conflicts"),
        draft=current.get("draft"),
        pipeline_status=(current.get("head_pipeline") or {}).get("status"),
        blocking_discussions_resolved=current.get("blocking_discussions_resolved"),
        next_step=next_step,
    )
    error = MergePendingError if waiting_helps else MergeBlockedError
    return error(f"GitLab refused to merge !{params.iid} ({status}). {next_step}", details=details)


def _with_draft_marker(title: str, draft: bool) -> str:
    bare = _DRAFT_MARKER.sub("", title, count=1)
    return f"Draft: {bare}" if draft else bare


MERGE_REQUESTS_TOOL = Tool(
    name="gitlab_merge_requests",
    title="GitLab merge requests",
    description=(
        "Find, open, update, merge, and rebase merge requests, and read their diffs and commits. "
        "Comments, threads, and approvals are in gitlab_mr_reviews."
    ),
    actions=(
        Action(
            "list",
            "List a project's merge requests.",
            ListMergeRequestsParams,
            list_merge_requests,
            Access.READ,
        ),
        Action(
            "get",
            "Get one merge request, including detailed_merge_status, has_conflicts, the head "
            "pipeline, and sha.",
            GetMergeRequestParams,
            get_merge_request,
            Access.READ,
        ),
        Action(
            "create",
            "Open a merge request.",
            CreateMergeRequestParams,
            create_merge_request,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a merge request's title, description, labels, assignees, target branch, or "
            "draft status.",
            UpdateMergeRequestParams,
            update_merge_request,
            Access.WRITE,
        ),
        Action(
            "close", "Close a merge request.", MergeRequestRef, close_merge_request, Access.WRITE
        ),
        Action(
            "reopen",
            "Reopen a closed merge request.",
            MergeRequestRef,
            reopen_merge_request,
            Access.WRITE,
        ),
        Action(
            "get_diff",
            "Summarize the changed files; full diff text only for include_diff_for paths.",
            DiffParams,
            get_diff,
            Access.READ,
        ),
        Action(
            "list_commits",
            "List the merge request's commits.",
            CommitsParams,
            list_commits,
            Access.READ,
        ),
        Action(
            "merge",
            "Merge now, or with auto_merge=true once checks pass. If GitLab refuses, the error "
            "says why and what to do next.",
            MergeParams,
            merge,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "rebase",
            "Rebase the source branch onto the target branch, in the background.",
            RebaseParams,
            rebase,
            Access.WRITE,
        ),
    ),
)
