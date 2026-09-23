"""gitlab_mr_reviews: threads, comments, draft reviews, and approvals on a merge request
(PRD-03 section 3)."""

from typing import Annotated, Any

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import (
    GitLabError,
    GitLabForbiddenError,
    GitLabNotFoundError,
    ToolError,
)
from mcp_gitlab.gitlab import Page
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets import threads
from mcp_gitlab.toolsets.common import with_hint
from mcp_gitlab.toolsets.merge_requests.merge_requests import MergeRequestRef


class ListDiscussions(MergeRequestRef, threads.ListDiscussionsFields):
    pass


class DiffPosition(MergeRequestRef):
    """Where on the diff a comment goes: a file, and a line in its new or old version."""

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
    def _position(self) -> "DiffPosition":
        has_line = self.new_line is not None or self.old_line is not None
        if has_line and not self.file_path:
            raise ValueError("new_line and old_line need file_path.")
        if self.file_path and not has_line:
            raise ValueError("file_path needs new_line, old_line, or both.")
        if self.old_path and not self.file_path:
            raise ValueError("old_path needs file_path.")
        return self


class CreateDiscussion(DiffPosition, threads.CreateDiscussionFields):
    pass


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


class ListReviewers(MergeRequestRef, PageParams):
    pass


DraftNoteId = Annotated[
    int, Field(ge=1, description="The draft's ID, from list_draft_notes or create_draft_note.")
]


class CreateDraftNote(DiffPosition):
    body: threads.Body
    discussion_id: threads.DiscussionId | None = Field(
        default=None,
        description="Reply in this existing thread, instead of starting a new one or commenting "
        "on a diff line.",
    )
    resolve_discussion: bool | None = Field(
        default=None, description="Resolve the thread named by discussion_id when this publishes."
    )

    @model_validator(mode="after")
    def _reply_or_new(self) -> "CreateDraftNote":
        if self.discussion_id and self.file_path:
            raise ValueError("Give discussion_id to reply, or file_path for a diff line, not both.")
        if self.resolve_discussion is not None and not self.discussion_id:
            raise ValueError("resolve_discussion needs discussion_id.")
        return self


class DraftNoteRef(MergeRequestRef):
    draft_note_id: DraftNoteId


class UpdateDraftNote(DraftNoteRef):
    body: threads.Body


class PublishReview(MergeRequestRef):
    body: threads.Body | None = Field(
        default=None, description="A summary comment, posted after the drafts."
    )
    internal: bool | None = Field(
        default=None, description="Make the comment internal, visible only to project members."
    )

    @model_validator(mode="after")
    def _internal_needs_body(self) -> "PublishReview":
        if self.internal is not None and not self.body:
            raise ValueError("internal applies to the summary comment: give body too.")
        return self


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
        raise with_hint(exc, hint) from exc


async def list_reviewers(params: ListReviewers, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(f"{params.path()}/reviewers", params=params.page_query())


async def list_draft_notes(params: MergeRequestRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{params.path()}/draft_notes")


async def create_draft_note(params: CreateDraftNote, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {"note": params.body}
    if params.discussion_id:
        body["in_reply_to_discussion_id"] = params.discussion_id
    if params.resolve_discussion is not None:
        body["resolve_discussion"] = params.resolve_discussion
    if params.file_path:
        body["position"] = await _diff_position(params, ctx)
    return await ctx.gitlab.post(f"{params.path()}/draft_notes", json_body=body)


async def update_draft_note(params: UpdateDraftNote, ctx: ActionContext) -> Any:
    # GitLab clears a draft's diff position unless the update sends it again, which would turn
    # a comment on a diff line into a general one.
    draft = await ctx.gitlab.get(_draft_note_path(params))
    body: dict[str, Any] = {"note": params.body}
    position = draft.get("position") if isinstance(draft, dict) else None
    if isinstance(position, dict) and position:
        body["position"] = _without_nulls(position)
    return await ctx.gitlab.put(_draft_note_path(params), json_body=body)


async def delete_draft_note(params: DraftNoteRef, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_draft_note_path(params))
    return {"deleted_draft_note": params.draft_note_id}


async def publish_draft_note(params: DraftNoteRef, ctx: ActionContext) -> Any:
    await ctx.gitlab.put(f"{_draft_note_path(params)}/publish")
    return {"published_draft_note": params.draft_note_id}


async def publish_review(params: PublishReview, ctx: ActionContext) -> Any:
    await ctx.gitlab.post(f"{params.path()}/draft_notes/bulk_publish")
    result: dict[str, Any] = {"published_review": params.iid}
    if params.body:
        # bulk_publish takes a summary only from GitLab 19.2, and earlier versions drop it
        # without an error, so the summary goes in as an ordinary comment.
        try:
            result["summary"] = await ctx.gitlab.post(
                f"{params.path()}/notes", json_body=params.fields()
            )
        except GitLabError as exc:
            hint = "The drafts were published, but not the summary: post it with create_note."
            raise with_hint(exc, hint) from exc
    return result


def _draft_note_path(params: DraftNoteRef) -> str:
    return f"{params.path()}/draft_notes/{params.draft_note_id}"


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    return value


async def _diff_position(params: DiffPosition, ctx: ActionContext) -> dict[str, Any]:
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
        "comments, draft comments published together as a review, and approvals."
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
        Action(
            "list_reviewers",
            "List the merge request's reviewers and each one's review state, such as "
            "unreviewed, reviewed, or requested_changes.",
            ListReviewers,
            list_reviewers,
            Access.READ,
        ),
        Action(
            "list_draft_notes",
            "List your unpublished review comments (drafts) on the merge request.",
            MergeRequestRef,
            list_draft_notes,
            Access.READ,
        ),
        Action(
            "create_draft_note",
            "Write a review comment that stays private until you publish it: on the merge "
            "request, on a diff line (file_path with new_line and/or old_line), or as a reply in "
            "a thread (discussion_id).",
            CreateDraftNote,
            create_draft_note,
            Access.WRITE,
        ),
        Action(
            "update_draft_note",
            "Change a draft's text.",
            UpdateDraftNote,
            update_draft_note,
            Access.WRITE,
        ),
        Action(
            "delete_draft_note",
            "Discard a draft.",
            DraftNoteRef,
            delete_draft_note,
            Access.WRITE,
        ),
        Action(
            "publish_draft_note",
            "Publish one draft now.",
            DraftNoteRef,
            publish_draft_note,
            Access.WRITE,
        ),
        Action(
            "publish_review",
            "Publish all your drafts at once as a review, optionally followed by a summary "
            "comment.",
            PublishReview,
            publish_review,
            Access.WRITE,
        ),
    ),
)
