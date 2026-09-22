"""gitlab_mr_reviews: threads, comments, and approvals on a merge request (PRD-03 section 3)."""

from typing import Any

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabForbiddenError, GitLabNotFoundError, ToolError
from mcp_gitlab.gitlab import Page
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets import threads
from mcp_gitlab.toolsets.merge_requests.merge_requests import MergeRequestRef


class ListDiscussions(MergeRequestRef, threads.ListDiscussionsFields):
    pass


class CreateDiscussion(MergeRequestRef, threads.CreateDiscussionFields):
    file_path: str | None = Field(
        default=None,
        min_length=1,
        description="Comment on a line of this file in the diff (its path after the change); "
        "give new_line, old_line, or both.",
    )
    old_path: str | None = Field(
        default=None,
        min_length=1,
        description="The file's path before the change, if it was renamed; defaults to file_path.",
    )
    new_line: int | None = Field(
        default=None,
        ge=1,
        description="Line number in the new version: an added or unchanged line.",
    )
    old_line: int | None = Field(
        default=None,
        ge=1,
        description="Line number in the old version: a removed or unchanged line (unchanged lines "
        "need both).",
    )

    @model_validator(mode="after")
    def _position(self) -> "CreateDiscussion":
        has_line = self.new_line is not None or self.old_line is not None
        if has_line and not self.file_path:
            raise ValueError("new_line and old_line need file_path.")
        if self.file_path and not has_line:
            raise ValueError("file_path needs new_line, old_line, or both.")
        if self.old_path and not self.file_path:
            raise ValueError("old_path needs file_path.")
        return self


class ReplyDiscussion(MergeRequestRef, threads.ReplyDiscussionFields):
    pass


class ResolveDiscussion(MergeRequestRef, threads.ResolveDiscussionFields):
    pass


class ListNotes(MergeRequestRef, threads.ListNotesFields):
    pass


class CreateNote(MergeRequestRef, threads.CreateNoteFields):
    pass


class UpdateNote(MergeRequestRef, threads.UpdateNoteFields):
    pass


class DeleteNote(MergeRequestRef, threads.DeleteNoteFields):
    pass


class ApproveParams(MergeRequestRef):
    sha: str | None = Field(
        default=None,
        min_length=1,
        description="Approve only if this is still the merge request's head commit (get's sha).",
    )


class ApprovalRulesParams(MergeRequestRef, PageParams):
    pass


class DiffNotReadyError(ToolError):
    code = "diff_not_ready"
    retryable = True


async def create_discussion(params: CreateDiscussion, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {"body": params.body}
    if params.file_path:
        body["position"] = await _diff_position(params, ctx)
    return await ctx.gitlab.post(f"{params.path()}/discussions", json_body=body)


async def list_approvals(params: MergeRequestRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{params.path()}/approvals")


async def approve(params: ApproveParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/approve", json_body=params.fields())


async def unapprove(params: MergeRequestRef, ctx: ActionContext) -> Any:
    await ctx.gitlab.post(f"{params.path()}/unapprove")
    return {"unapproved": params.iid}


async def list_approval_rules(params: ApprovalRulesParams, ctx: ActionContext) -> Page:
    try:
        return await ctx.gitlab.get_page(
            f"{params.path()}/approval_rules", params=params.page_query()
        )
    except (GitLabForbiddenError, GitLabNotFoundError) as exc:
        hint = (
            "Approval rules need GitLab Premium or Ultimate, so this fails on GitLab Free; "
            "list_approvals shows who approved on every tier."
        )
        raise type(exc)(
            f"{exc.message} {hint}", status=exc.status, details={**exc.details, "hint": hint}
        ) from exc


async def _diff_position(params: CreateDiscussion, ctx: ActionContext) -> dict[str, Any]:
    """GitLab anchors a diff comment to the merge request's current diff version."""
    merge_request = await ctx.gitlab.get(params.path())
    refs = merge_request.get("diff_refs") or {}
    if not all(refs.get(key) for key in ("base_sha", "head_sha", "start_sha")):
        raise DiffNotReadyError(
            f"GitLab has not finished computing the diff of !{params.iid} yet; retry shortly."
        )
    position: dict[str, Any] = {
        "position_type": "text",
        "base_sha": refs["base_sha"],
        "head_sha": refs["head_sha"],
        "start_sha": refs["start_sha"],
        "new_path": params.file_path,
        "old_path": params.old_path or params.file_path,
    }
    if params.new_line is not None:
        position["new_line"] = params.new_line
    if params.old_line is not None:
        position["old_line"] = params.old_line
    return position


MR_REVIEWS_TOOL = Tool(
    name="gitlab_mr_reviews",
    title="GitLab merge request reviews",
    description=(
        "Review a merge request: threads (including comments on specific diff lines), plain "
        "comments, and approvals."
    ),
    actions=(
        *threads.thread_actions(
            "merge request",
            threads.ThreadParams(
                list_discussions=ListDiscussions,
                create_discussion=CreateDiscussion,
                reply_discussion=ReplyDiscussion,
                resolve_discussion=ResolveDiscussion,
                list_notes=ListNotes,
                create_note=CreateNote,
                update_note=UpdateNote,
                delete_note=DeleteNote,
            ),
            create_discussion_handler=create_discussion,
            create_discussion_description="Start a thread on the merge request. To comment on a "
            "diff line, give file_path with new_line (added line), old_line (removed line), or "
            "both (unchanged line).",
        ),
        Action(
            "list_approvals",
            "Show the approval state: whether it is approved and by whom.",
            MergeRequestRef,
            list_approvals,
            Access.READ,
        ),
        Action("approve", "Approve the merge request.", ApproveParams, approve, Access.WRITE),
        Action("unapprove", "Withdraw your approval.", MergeRequestRef, unapprove, Access.WRITE),
        Action(
            "list_approval_rules",
            "List the approval rules that apply (read-only; GitLab Premium or Ultimate).",
            ApprovalRulesParams,
            list_approval_rules,
            Access.READ,
        ),
    ),
)
