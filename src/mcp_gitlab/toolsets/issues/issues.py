"""gitlab_issues: issues, their state, moving them, and related-issue links (PRD-04 s.3)."""

from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabForbiddenError
from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import IsoDate, ProjectRef, query, with_csv_labels, with_hint
from mcp_gitlab.toolsets.threads import NoteableRef

IssueIid = Annotated[
    int, Field(ge=1, description="The issue's IID: the number shown as #34 in GitLab.")
]
UserId = Annotated[int, Field(ge=1)]
Labels = Annotated[
    list[str] | None,
    Field(
        default=None,
        description="Label names. list matches issues that have all of them; create and update "
        "set exactly these, replacing any others.",
    ),
]
AssigneeIds = Annotated[
    list[UserId] | None,
    Field(
        default=None,
        description="Assignee user IDs, replacing any others (GitLab Free allows one); an empty "
        "list unassigns everyone.",
    ),
]
MilestoneId = Annotated[
    int | None,
    Field(default=None, ge=1, description="Milestone ID, from gitlab_milestones."),
]
DueDate = Annotated[IsoDate | None, Field(default=None, description="Due date, as YYYY-MM-DD.")]
Confidential = Annotated[
    bool | None,
    Field(default=None, description="Confidential issues are visible only to project members."),
]
LinkType = Literal["relates_to", "blocks", "is_blocked_by"]


class IssueRef(NoteableRef):
    collection: ClassVar[str] = "issues"
    iid_field: ClassVar[str] = "issue_iid"

    issue_iid: IssueIid


class ListIssuesParams(PageParams):
    project: ProjectRef
    state: Literal["opened", "closed", "all"] = Field(
        default="opened", description="Which issues to list; open ones unless you ask otherwise."
    )
    labels: Labels
    milestone: str | None = Field(default=None, description="Milestone title.")
    assignee_id: UserId | None = Field(default=None, description="Assignee's user ID.")
    author_id: UserId | None = Field(default=None, description="Author's user ID.")
    search: str | None = Field(default=None, description="Match the title or description.")


class CreateIssueParams(ActionParams):
    project: ProjectRef
    title: str = Field(min_length=1, description="Issue title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    labels: Labels
    assignee_ids: AssigneeIds
    milestone_id: MilestoneId
    due_date: DueDate
    confidential: Confidential


class UpdateIssueParams(IssueRef):
    title: str | None = Field(default=None, min_length=1, description="Issue title.")
    description: str | None = Field(default=None, description="Description, in Markdown.")
    labels: Labels
    assignee_ids: AssigneeIds
    milestone_id: MilestoneId
    due_date: DueDate
    confidential: Confidential

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateIssueParams":
        if not self.fields():
            raise ValueError("Nothing to update: set at least one field.")
        return self


class MoveIssueParams(IssueRef):
    to_project: ProjectRef = Field(description="Project to move the issue to: ID or full path.")


class LinkIssueParams(IssueRef):
    target_project: ProjectRef = Field(
        description="Project of the issue to link to: ID or full path (often the same project)."
    )
    target_issue_iid: IssueIid = Field(description="IID of the issue to link to.")
    link_type: LinkType | None = Field(
        default=None,
        description="relates_to (the default), blocks, or is_blocked_by; the last two need "
        "GitLab Premium.",
    )


class UnlinkIssueParams(IssueRef):
    issue_link_id: int = Field(ge=1, description="The link's ID, from list_links.")


async def list_issues(params: ListIssuesParams, ctx: ActionContext) -> Page:
    fields = with_csv_labels(query(params, "state"))
    if params.state != "all":  # GitLab itself returns every state when none is given
        fields["state"] = params.state
    return await ctx.gitlab.get_page(f"{project_path(params.project)}/issues", params=fields)


async def get_issue(params: IssueRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(params.path())


async def create_issue(params: CreateIssueParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/issues", json_body=with_csv_labels(query(params))
    )


async def update_issue(params: UpdateIssueParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(params.path(), json_body=with_csv_labels(params.fields()))


async def close_issue(params: IssueRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(params.path(), json_body={"state_event": "close"})


async def reopen_issue(params: IssueRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(params.path(), json_body={"state_event": "reopen"})


async def delete_issue(params: IssueRef, ctx: ActionContext) -> Any:
    try:
        await ctx.gitlab.delete(params.path())
    except GitLabForbiddenError as exc:
        hint = (
            "Only members with the Planner or Owner role can delete any issue; others can delete "
            "only issues they authored (GitLab 18.10 and later). Consider close instead, which "
            "needs fewer permissions."
        )
        raise with_hint(exc, hint) from exc
    return {"deleted": params.iid}


async def move_issue(params: MoveIssueParams, ctx: ActionContext) -> Any:
    target = await _project_id(params.to_project, ctx)
    return await ctx.gitlab.post(f"{params.path()}/move", json_body={"to_project_id": target})


async def list_links(params: IssueRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{params.path()}/links")


async def link_issue(params: LinkIssueParams, ctx: ActionContext) -> Any:
    body: dict[str, Any] = {
        "target_project_id": params.target_project,
        "target_issue_iid": params.target_issue_iid,
    }
    if params.link_type is not None:
        body["link_type"] = params.link_type
    return await ctx.gitlab.post(f"{params.path()}/links", json_body=body)


async def unlink_issue(params: UnlinkIssueParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.delete(f"{params.path()}/links/{params.issue_link_id}")


async def _project_id(project: int | str, ctx: ActionContext) -> int:
    """GitLab's move endpoint takes only a numeric project ID."""
    if isinstance(project, int):
        return project
    if project.isdigit():
        return int(project)
    found = await ctx.gitlab.get(f"/projects/{encode_segment(project)}")
    return int(found["id"])


ISSUES_TOOL = Tool(
    name="gitlab_issues",
    title="GitLab issues",
    description=(
        "Find, create, update, close, move, and link issues. Comments are in "
        "gitlab_issue_notes; labels and milestones have their own tools."
    ),
    actions=(
        Action(
            "list",
            "List a project's issues; open ones unless state says otherwise.",
            ListIssuesParams,
            list_issues,
            Access.READ,
        ),
        Action("get", "Get one issue.", IssueRef, get_issue, Access.READ),
        Action("create", "Create an issue.", CreateIssueParams, create_issue, Access.WRITE),
        Action(
            "update",
            "Change an issue's title, description, labels, assignees, milestone, due date, or "
            "confidentiality.",
            UpdateIssueParams,
            update_issue,
            Access.WRITE,
        ),
        Action("close", "Close an issue.", IssueRef, close_issue, Access.WRITE),
        Action("reopen", "Reopen a closed issue.", IssueRef, reopen_issue, Access.WRITE),
        Action(
            "delete",
            "Delete an issue permanently (closing is usually what you want).",
            IssueRef,
            delete_issue,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "move", "Move an issue to another project.", MoveIssueParams, move_issue, Access.WRITE
        ),
        Action(
            "list_links",
            "List the issues linked to this one, with each link's ID and type.",
            IssueRef,
            list_links,
            Access.READ,
        ),
        Action("link", "Link this issue to another.", LinkIssueParams, link_issue, Access.WRITE),
        Action(
            "unlink",
            "Remove a link between issues.",
            UnlinkIssueParams,
            unlink_issue,
            Access.WRITE,
        ),
    ),
)
