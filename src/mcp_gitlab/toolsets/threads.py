"""Discussions (threads) and notes, shared by merge requests (PRD-03) and issues (PRD-04).

GitLab exposes the same comment API on both: `/<collection>/:iid/discussions` for threads and
`/<collection>/:iid/notes` for plain comments. Each toolset declares a `NoteableRef` subclass
naming its collection and IID parameter, combines it with the field mixins below, and passes
the resulting classes to `thread_actions`.
"""

from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams
from mcp_gitlab.toolsets.common import ProjectRef

Body = Annotated[str, Field(min_length=1, description="Comment text, in Markdown.")]
DiscussionId = Annotated[
    str, Field(min_length=1, description="Thread ID, as returned by list_discussions.")
]
NoteId = Annotated[int, Field(ge=1, description="Note (comment) ID.")]


class NoteableRef(ActionParams):
    """One merge request or issue: anything GitLab lets you comment on."""

    collection: ClassVar[str]
    iid_field: ClassVar[str]

    project: ProjectRef

    @property
    def iid(self) -> int:
        return int(getattr(self, self.iid_field))

    def path(self) -> str:
        return f"{project_path(self.project)}/{self.collection}/{self.iid}"

    def fields(self, *exclude: str) -> dict[str, Any]:
        """Set parameters other than the path ones, for a GitLab query or body."""
        return self.model_dump(exclude={"project", self.iid_field, *exclude}, exclude_none=True)


class ListDiscussionsFields(NoteableRef, PageParams):
    pass


class CreateDiscussionFields(NoteableRef):
    body: Body


class ReplyDiscussionFields(NoteableRef):
    discussion_id: DiscussionId
    body: Body


class ResolveDiscussionFields(NoteableRef):
    discussion_id: DiscussionId
    resolved: bool = Field(default=True, description="true resolves the thread; false reopens it.")


class ListNotesFields(NoteableRef, PageParams):
    sort: Literal["asc", "desc"] | None = Field(
        default=None, description="Sort direction; GitLab defaults to desc (newest first)."
    )
    order_by: Literal["created_at", "updated_at"] | None = Field(
        default=None, description="Field to order by; GitLab defaults to created_at."
    )


class CreateNoteFields(NoteableRef):
    body: Body
    internal: bool | None = Field(
        default=None, description="Make the comment internal, visible only to project members."
    )


class UpdateNoteFields(NoteableRef):
    note_id: NoteId
    body: Body
    discussion_id: DiscussionId | None = Field(
        default=None, description="The thread the note belongs to, when it is a thread reply."
    )


class DeleteNoteFields(NoteableRef):
    note_id: NoteId
    discussion_id: DiscussionId | None = Field(
        default=None, description="The thread the note belongs to, when it is a thread reply."
    )


async def list_discussions(params: ListDiscussionsFields, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(f"{params.path()}/discussions", params=params.page_query())


async def create_discussion(params: CreateDiscussionFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/discussions", json_body={"body": params.body})


async def reply_discussion(params: ReplyDiscussionFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{_discussion_path(params, params.discussion_id)}/notes", json_body={"body": params.body}
    )


async def resolve_discussion(params: ResolveDiscussionFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(
        _discussion_path(params, params.discussion_id), json_body={"resolved": params.resolved}
    )


async def list_notes(params: ListNotesFields, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{params.path()}/notes",
        params={**params.page_query(), **params.fields("page", "per_page")},
    )


async def create_note(params: CreateNoteFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/notes", json_body=params.fields())


async def update_note(params: UpdateNoteFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(
        _note_path(params, params.note_id, params.discussion_id), json_body={"body": params.body}
    )


async def delete_note(params: DeleteNoteFields, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_note_path(params, params.note_id, params.discussion_id))
    return {"deleted_note": params.note_id}


def _discussion_path(params: NoteableRef, discussion_id: str) -> str:
    return f"{params.path()}/discussions/{encode_segment(discussion_id)}"


def _note_path(params: NoteableRef, note_id: int, discussion_id: str | None) -> str:
    if discussion_id:
        return f"{_discussion_path(params, discussion_id)}/notes/{note_id}"
    return f"{params.path()}/notes/{note_id}"


@dataclass(frozen=True)
class ThreadParams:
    """The concrete parameter classes one toolset built from the mixins above."""

    list_discussions: type[ListDiscussionsFields]
    create_discussion: type[CreateDiscussionFields]
    reply_discussion: type[ReplyDiscussionFields]
    list_notes: type[ListNotesFields]
    create_note: type[CreateNoteFields]
    update_note: type[UpdateNoteFields]
    delete_note: type[DeleteNoteFields]
    resolve_discussion: type[ResolveDiscussionFields] | None = None


def thread_actions(
    label: str,
    params: ThreadParams,
    *,
    create_discussion_handler: Any = create_discussion,
    create_discussion_description: str | None = None,
) -> tuple[Action, ...]:
    """The standard comment actions for one kind of noteable, such as "merge request"."""
    actions = [
        Action(
            "list_discussions",
            f"List the {label}'s threads with their replies.",
            params.list_discussions,
            list_discussions,
            Access.READ,
        ),
        Action(
            "create_discussion",
            create_discussion_description or f"Start a new thread on the {label}.",
            params.create_discussion,
            create_discussion_handler,
            Access.WRITE,
        ),
        Action(
            "reply_discussion",
            "Reply in an existing thread.",
            params.reply_discussion,
            reply_discussion,
            Access.WRITE,
        ),
    ]
    if params.resolve_discussion is not None:
        actions.append(
            Action(
                "resolve_discussion",
                "Resolve a thread, or reopen it with resolved=false.",
                params.resolve_discussion,
                resolve_discussion,
                Access.WRITE,
            )
        )
    actions += [
        Action(
            "list_notes",
            f"List the {label}'s top-level comments and system notes (not thread replies).",
            params.list_notes,
            list_notes,
            Access.READ,
        ),
        Action(
            "create_note",
            f"Add a plain comment to the {label}.",
            params.create_note,
            create_note,
            Access.WRITE,
        ),
        Action(
            "update_note",
            "Edit a comment; give discussion_id when it is a reply in a thread.",
            params.update_note,
            update_note,
            Access.WRITE,
        ),
        Action(
            "delete_note",
            "Delete a comment; give discussion_id when it is a reply in a thread.",
            params.delete_note,
            delete_note,
            Access.WRITE,
        ),
    ]
    return tuple(actions)
