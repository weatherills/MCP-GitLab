"""gitlab_members: who can access a project, and with which role (PRD-08 section 3).

Roles are accepted by name or by GitLab's number, and every member returned carries
access_level_name next to GitLab's numeric access_level (PRD-08 section 4).
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabConflictError, GitLabNotFoundError
from mcp_gitlab.gitlab import Page, group_path, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import IsoDate, NamespaceRef, ProjectRef, query, with_hint

ROLE_LEVELS: dict[str, int] = {
    "guest": 10,
    "planner": 15,
    "reporter": 20,
    "security_manager": 25,
    "developer": 30,
    "maintainer": 40,
    "owner": 50,
}
# Every level GitLab can report, including those no project member can be given.
LEVEL_NAMES: dict[int, str] = {
    0: "no_access",
    5: "minimal_access",
    **{level: name for name, level in ROLE_LEVELS.items()},
    60: "admin",
}

Role = Annotated[
    Literal["guest", "planner", "reporter", "security_manager", "developer", "maintainer", "owner"]
    | Literal[10, 15, 20, 25, 30, 40, 50],
    Field(
        description="Role, by name or GitLab's number: guest (10), planner (15), reporter (20), "
        "security_manager (25), developer (30), maintainer (40), or owner (50)."
    ),
]
UserId = Annotated[
    int, Field(ge=1, description="The user's numeric ID; gitlab_users finds it from a username.")
]
Inherited = Annotated[
    bool,
    Field(
        default=False,
        description="Also include members who get access through parent or invited groups, "
        "each with their effective (highest) role. Default: direct members only.",
    ),
]
MemberQuery = Annotated[
    str | None,
    Field(default=None, min_length=1, description="Filter by name, email, or username."),
]
ExpiresAt = Annotated[
    IsoDate | None,
    Field(default=None, description="Date the membership ends, as YYYY-MM-DD."),
]

NOT_DIRECT_HINT = (
    "If the user gets access through a parent group, they are not a direct member of this "
    "project: change their access on that group instead (list_group_members shows it)."
)


class ListMembersParams(PageParams):
    project: ProjectRef
    inherited: Inherited
    query: MemberQuery


class ListGroupMembersParams(PageParams):
    group: NamespaceRef = Field(description="Group ID, or its full path such as parent/child.")
    inherited: Inherited
    query: MemberQuery


class MemberParams(ActionParams):
    project: ProjectRef
    user_id: UserId


class GetMemberParams(MemberParams):
    inherited: Inherited


class AddMemberParams(ActionParams):
    project: ProjectRef
    user_id: UserId | None = Field(default=None, description="The user's numeric ID.")
    username: str | None = Field(
        default=None, min_length=1, description="The user's username, instead of user_id."
    )
    access_level: Role
    expires_at: ExpiresAt

    @model_validator(mode="after")
    def _one_user(self) -> "AddMemberParams":
        if (self.user_id is None) == (self.username is None):
            raise ValueError("Give exactly one of user_id or username.")
        return self


class UpdateMemberParams(MemberParams):
    access_level: Role
    expires_at: ExpiresAt


class RemoveMemberParams(MemberParams):
    unassign_issuables: bool | None = Field(
        default=None,
        description="Also unassign the user from this project's issues and merge requests.",
    )


async def list_members(params: ListMembersParams, ctx: ActionContext) -> Page:
    path = f"{project_path(params.project)}/members{'/all' if params.inherited else ''}"
    return named(await ctx.gitlab.get_page(path, params=query(params, "inherited")))


async def list_group_members(params: ListGroupMembersParams, ctx: ActionContext) -> Page:
    path = f"{group_path(params.group)}/members{'/all' if params.inherited else ''}"
    return named(await ctx.gitlab.get_page(path, params=query(params, "group", "inherited")))


async def get_member(params: GetMemberParams, ctx: ActionContext) -> Any:
    scope = "all/" if params.inherited else ""
    try:
        member = await ctx.gitlab.get(
            f"{project_path(params.project)}/members/{scope}{params.user_id}"
        )
    except GitLabNotFoundError as exc:
        if params.inherited:
            raise
        raise with_hint(
            exc, "Set inherited to true to find access that comes through a group."
        ) from exc
    return with_role_name(member)


async def add_member(params: AddMemberParams, ctx: ActionContext) -> Any:
    body = {**query(params), "access_level": level_of(params.access_level)}
    try:
        member = await ctx.gitlab.post(f"{project_path(params.project)}/members", json_body=body)
    except GitLabConflictError as exc:
        raise with_hint(
            exc, "The user is already a direct member; use update to change their role."
        ) from exc
    return with_role_name(member)


async def update_member(params: UpdateMemberParams, ctx: ActionContext) -> Any:
    body = {**query(params, "user_id"), "access_level": level_of(params.access_level)}
    try:
        member = await ctx.gitlab.put(_member_path(params), json_body=body)
    except GitLabNotFoundError as exc:
        raise with_hint(exc, NOT_DIRECT_HINT) from exc
    return with_role_name(member)


async def remove_member(params: RemoveMemberParams, ctx: ActionContext) -> Any:
    try:
        await ctx.gitlab.delete(_member_path(params), params=query(params, "user_id"))
    except GitLabNotFoundError as exc:
        raise with_hint(exc, NOT_DIRECT_HINT) from exc
    return {"removed": params.user_id}


def level_of(role: str | int) -> int:
    return ROLE_LEVELS[role] if isinstance(role, str) else role


def with_role_name(member: Any) -> Any:
    """Add access_level_name next to GitLab's numeric access_level."""
    level = member.get("access_level") if isinstance(member, dict) else None
    if not isinstance(level, int) or level not in LEVEL_NAMES:
        return member
    return {**member, "access_level_name": LEVEL_NAMES[level]}


def named(page: Page) -> Page:
    return Page(items=[with_role_name(member) for member in page.items], info=page.info)


def _member_path(params: MemberParams) -> str:
    return f"{project_path(params.project)}/members/{params.user_id}"


MEMBERS_TOOL = Tool(
    name="gitlab_members",
    title="GitLab project members",
    description=(
        "See and manage who can access a project and with which role. Roles are given and "
        "returned by name (guest, planner, reporter, security_manager, developer, maintainer, "
        "owner) as well as GitLab's number. Only direct members can be changed here."
    ),
    actions=(
        Action(
            "list",
            "List a project's members; inherited: true adds those with access through groups.",
            ListMembersParams,
            list_members,
            Access.READ,
        ),
        Action(
            "get",
            "Get one member's role and expiry; inherited: true includes group access.",
            GetMemberParams,
            get_member,
            Access.READ,
        ),
        Action(
            "add",
            "Add a user as a direct member, with a role and an optional end date.",
            AddMemberParams,
            add_member,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a direct member's role or end date. Lowering an owner's role, including "
            "your own, can lock people out.",
            UpdateMemberParams,
            update_member,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "remove",
            "Remove a direct member. Removing yourself revokes your own access.",
            RemoveMemberParams,
            remove_member,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "list_group_members",
            "List a group's members, to see where a project member's access comes from.",
            ListGroupMembersParams,
            list_group_members,
            Access.READ,
        ),
    ),
)
