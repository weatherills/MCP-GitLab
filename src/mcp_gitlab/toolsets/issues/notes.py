"""gitlab_issue_notes: threads and comments on an issue (PRD-04 section 3).

GitLab's API cannot resolve issue threads (only merge request threads), so unlike
gitlab_mr_reviews there is no resolve_discussion here.
"""

from typing import Literal

from pydantic import Field

from mcp_gitlab.tools import Tool
from mcp_gitlab.toolsets import threads
from mcp_gitlab.toolsets.issues.issues import IssueRef


class ListDiscussions(IssueRef, threads.ListDiscussionsFields):
    pass


class CreateDiscussion(IssueRef, threads.CreateDiscussionFields):
    pass


class ReplyDiscussion(IssueRef, threads.ReplyDiscussionFields):
    pass


class ListNotes(IssueRef, threads.ListNotesFields):
    activity_filter: Literal["all_notes", "only_comments", "only_activity"] | None = Field(
        default=None,
        description="only_comments skips system notes such as label changes; GitLab defaults "
        "to all_notes.",
    )


class CreateNote(IssueRef, threads.CreateNoteFields):
    pass


class UpdateNote(IssueRef, threads.UpdateNoteFields):
    pass


class DeleteNote(IssueRef, threads.DeleteNoteFields):
    pass


ISSUE_NOTES_TOOL = Tool(
    name="gitlab_issue_notes",
    title="GitLab issue comments",
    description="Comment on an issue: threads, replies, and plain comments.",
    actions=threads.thread_actions(
        "issue",
        threads.ThreadParams(
            list_discussions=ListDiscussions,
            create_discussion=CreateDiscussion,
            reply_discussion=ReplyDiscussion,
            list_notes=ListNotes,
            create_note=CreateNote,
            update_note=UpdateNote,
            delete_note=DeleteNote,
        ),
    ),
)
