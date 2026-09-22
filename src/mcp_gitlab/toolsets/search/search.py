"""gitlab_search: instance, group, and project search with compact results (PRD-07).

Results are trimmed to what identifies a match (IDs, paths, titles, the matched lines), so the
model fetches full detail from the matching domain tool afterwards (PRD-07 section 4).
"""

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabBadRequestError, GitLabForbiddenError, ToolError
from mcp_gitlab.gitlab import Page, group_path, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets.common import NamespaceRef, ProjectRef

Scope = Literal[
    "projects",
    "groups",
    "issues",
    "work_items",
    "merge_requests",
    "milestones",
    "snippet_titles",
    "users",
    "wiki_blobs",
    "commits",
    "blobs",
    "notes",
]
PROJECT_SCOPES = frozenset(
    {
        "issues",
        "work_items",
        "merge_requests",
        "milestones",
        "users",
        "wiki_blobs",
        "commits",
        "blobs",
        "notes",
    }
)
GROUP_SCOPES = PROJECT_SCOPES | {"projects", "groups"}
GLOBAL_SCOPES = GROUP_SCOPES | {"snippet_titles"}
# Across an instance or group these need Advanced Search (GitLab Premium); in one project they
# work with basic search.
ADVANCED_SCOPES = frozenset({"wiki_blobs", "commits", "blobs", "notes"})

_FIELDS: dict[str, tuple[str, ...]] = {
    "projects": (
        "id",
        "path_with_namespace",
        "name",
        "description",
        "default_branch",
        "web_url",
        "last_activity_at",
    ),
    "groups": ("id", "full_path", "name", "web_url"),
    "issues": (
        "id",
        "iid",
        "project_id",
        "title",
        "state",
        "labels",
        "author",
        "updated_at",
        "web_url",
    ),
    "work_items": (
        "id",
        "iid",
        "project_id",
        "title",
        "type",
        "state",
        "labels",
        "author",
        "updated_at",
        "web_url",
    ),
    "merge_requests": (
        "id",
        "iid",
        "project_id",
        "title",
        "state",
        "source_branch",
        "target_branch",
        "author",
        "updated_at",
        "web_url",
    ),
    "milestones": ("id", "iid", "project_id", "title", "state", "due_date"),
    "snippet_titles": ("id", "title", "file_name", "project_id", "web_url"),
    "users": ("id", "username", "name", "state", "web_url"),
    "wiki_blobs": ("path", "ref", "startline", "data", "project_id", "group_id"),
    "commits": ("id", "short_id", "title", "author_name", "authored_date", "project_id"),
    "blobs": ("path", "ref", "startline", "data", "project_id"),
    "notes": ("id", "body", "author", "noteable_type", "noteable_iid", "project_id", "created_at"),
}
_TRUNCATE = {"description": 200, "body": 300}

ScopeField = Field(
    description="What to search. projects and groups work in global and group search, "
    "snippet_titles only in global search. blobs (code), commits, wiki_blobs, and notes need "
    "GitLab Advanced Search in global and group search, but always work in project search."
)
SearchField = Field(min_length=1, description="The search term.")
StateField = Field(
    default=None, description="For issues and merge requests: only those in this state."
)


class AdvancedSearchUnavailableError(ToolError):
    code = "advanced_search_unavailable"


class _SearchParams(PageParams):
    allowed: ClassVar[frozenset[str]] = GLOBAL_SCOPES
    level: ClassVar[str] = "global"

    scope: Scope = ScopeField
    search: str = SearchField
    state: Literal["opened", "closed", "merged", "all"] | None = StateField

    @model_validator(mode="after")
    def _scope_available(self) -> "_SearchParams":
        if self.scope not in self.allowed:
            available = ", ".join(sorted(self.allowed))
            raise ValueError(
                f"{self.level} search has no '{self.scope}' scope; use one of: {available}."
            )
        return self


class GlobalSearchParams(_SearchParams):
    pass


class GroupSearchParams(_SearchParams):
    allowed: ClassVar[frozenset[str]] = GROUP_SCOPES
    level: ClassVar[str] = "group"

    group: NamespaceRef = Field(description="Group ID, or its full path such as parent/child.")


class ProjectSearchParams(_SearchParams):
    allowed: ClassVar[frozenset[str]] = PROJECT_SCOPES
    level: ClassVar[str] = "project"

    project: ProjectRef
    ref: str | None = Field(
        default=None,
        min_length=1,
        description="Branch or tag to search for blobs, commits, and wiki_blobs; the default "
        "branch if omitted.",
    )


async def search_global(params: GlobalSearchParams, ctx: ActionContext) -> Any:
    return await _search("/search", params, ctx, cross_project=True)


async def search_group(params: GroupSearchParams, ctx: ActionContext) -> Any:
    return await _search(f"{group_path(params.group)}/search", params, ctx, cross_project=True)


async def search_project(params: ProjectSearchParams, ctx: ActionContext) -> Any:
    extra = {"ref": params.ref} if params.ref else {}
    return await _search(
        f"{project_path(params.project)}/search", params, ctx, cross_project=False, extra=extra
    )


async def _search(
    path: str,
    params: _SearchParams,
    ctx: ActionContext,
    *,
    cross_project: bool,
    extra: Mapping[str, Any] | None = None,
) -> Any:
    query: dict[str, Any] = {
        **params.page_query(),
        "scope": params.scope,
        "search": params.search,
        **(extra or {}),
    }
    if params.state and params.state != "all":
        query["state"] = params.state
    needs_advanced = cross_project and params.scope in ADVANCED_SCOPES
    try:
        page = await ctx.gitlab.get_page(path, params=query)
    except (GitLabBadRequestError, GitLabForbiddenError) as exc:
        if not needs_advanced:
            raise
        raise AdvancedSearchUnavailableError(
            f"GitLab refused a {params.level} search of {params.scope}: across projects this "
            "needs Advanced Search (GitLab Premium with Elasticsearch or exact code search), "
            "which this instance does not offer. Use the project action on each candidate "
            "project instead; there it works with basic search.",
            details={"gitlab_message": exc.details.get("gitlab_message"), "scope": params.scope},
        ) from exc
    result = Page(items=[compact(params.scope, item) for item in page.items], info=page.info)
    if needs_advanced and not page.items:
        return {
            **result.to_dict(),
            "note": f"No matches. If this instance lacks Advanced Search, {params.level} search "
            f"of {params.scope} always comes back empty; the project action searches one "
            "project without it.",
        }
    return result


def compact(scope: str, item: Any) -> Any:
    """Keep the fields that identify a match; the domain tools return the rest."""
    if not isinstance(item, dict):
        return item
    trimmed: dict[str, Any] = {}
    for key in _FIELDS.get(scope, tuple(item)):
        if key not in item:
            continue
        value = item[key]
        if key == "author" and isinstance(value, dict):
            value = value.get("username")
        limit = _TRUNCATE.get(key)
        if limit and isinstance(value, str) and len(value) > limit:
            value = value[:limit] + "…"
        trimmed[key] = value
    return trimmed


SEARCH_TOOL = Tool(
    name="gitlab_search",
    title="GitLab search",
    description=(
        "Search GitLab across the instance, a group, or a project. Results are compact (IDs, "
        "paths, titles, matched lines); fetch full detail with the matching tool, such as "
        "gitlab_files get or gitlab_issues get. Code search across projects needs GitLab "
        "Advanced Search; project search always works."
    ),
    actions=(
        Action(
            "global",
            "Search everything the caller can see.",
            GlobalSearchParams,
            search_global,
            Access.READ,
        ),
        Action(
            "group",
            "Search within one group and its subgroups.",
            GroupSearchParams,
            search_group,
            Access.READ,
        ),
        Action(
            "project",
            "Search one project, including its code (blobs) and commits.",
            ProjectSearchParams,
            search_project,
            Access.READ,
        ),
    ),
)
