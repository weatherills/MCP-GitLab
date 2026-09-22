"""gitlab_users: read-only user lookup, including who the calling token belongs to (PRD-08 s.3).

Account administration (create, block, delete) is out of scope (PRD-08 section 5).
"""

from typing import Any

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabError, GitLabNotFoundError
from mcp_gitlab.gitlab import Page
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, NoParams, PageParams, Tool
from mcp_gitlab.toolsets.common import query

# GitLab serves these endpoints to tokens with only the read_user scope, too.
USER_SCOPES = frozenset({"api", "read_api", "read_user"})
# What get_current reports about the calling token: never the token itself.
TOKEN_FIELDS = ("name", "scopes", "expires_at", "last_used_at", "active")


class GetUserParams(ActionParams):
    user_id: int | None = Field(default=None, ge=1, description="The user's numeric ID.")
    username: str | None = Field(
        default=None, min_length=1, description="The user's username, instead of user_id."
    )

    @model_validator(mode="after")
    def _one_user(self) -> "GetUserParams":
        if (self.user_id is None) == (self.username is None):
            raise ValueError("Give exactly one of user_id or username.")
        return self


class SearchUsersParams(PageParams):
    search: str = Field(
        min_length=1,
        description="Part of a name or username, or a full public email address.",
    )


async def get_current_user(params: NoParams, ctx: ActionContext) -> Any:
    user = await ctx.gitlab.get("/user")
    try:
        token = await ctx.gitlab.get("/personal_access_tokens/self")
    except GitLabError:
        # Not a personal access token, or GitLab won't say: the user is still the answer.
        return user
    if not isinstance(user, dict) or not isinstance(token, dict):
        return user
    return {**user, "token_info": {key: token[key] for key in TOKEN_FIELDS if key in token}}


async def get_user(params: GetUserParams, ctx: ActionContext) -> Any:
    user_id = params.user_id
    if user_id is None:
        matches = await ctx.gitlab.get("/users", params={"username": params.username})
        if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
            raise GitLabNotFoundError(f"No GitLab user has the username '{params.username}'.")
        user_id = matches[0]["id"]
    return await ctx.gitlab.get(f"/users/{user_id}")


async def search_users(params: SearchUsersParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page("/users", params=query(params))


USERS_TOOL = Tool(
    name="gitlab_users",
    title="GitLab users",
    description=(
        "Look up GitLab users (read-only): who the calling token belongs to, one user by ID or "
        "username, or a search by name."
    ),
    actions=(
        Action(
            "get_current",
            "Who am I: the user behind the calling token, plus the token's name, scopes, and "
            "expiry when GitLab reports them.",
            NoParams,
            get_current_user,
            Access.READ,
            scopes=USER_SCOPES,
        ),
        Action(
            "get",
            "Get one user's public profile by user_id or username.",
            GetUserParams,
            get_user,
            Access.READ,
            scopes=USER_SCOPES,
        ),
        Action(
            "search",
            "Find users by name, username, or public email.",
            SearchUsersParams,
            search_users,
            Access.READ,
            scopes=USER_SCOPES,
        ),
    ),
)
