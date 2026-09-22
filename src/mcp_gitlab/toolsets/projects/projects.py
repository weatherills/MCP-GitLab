"""gitlab_projects: the project (repository) lifecycle (PRD-01 section 3)."""

from typing import Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabError, GitLabNotFoundError
from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import NamespaceRef, ProjectRef, Visibility, query


class ListProjectsParams(PageParams):
    search: str | None = Field(
        default=None, description="Match project path, name, or description."
    )
    owned: bool | None = Field(default=None, description="Only projects the caller owns.")
    membership: bool | None = Field(
        default=None, description="Only projects the caller is a member of."
    )
    visibility: Visibility | None = Field(default=None, description="Visibility level.")
    archived: bool | None = Field(default=None, description="Filter by archived status.")
    simple: bool = Field(default=True, description="Return only core fields for each project.")


class ProjectParams(ActionParams):
    project: ProjectRef


class ListForksParams(PageParams):
    project: ProjectRef
    search: str | None = Field(
        default=None, description="Match project path, name, or description."
    )
    simple: bool = Field(default=True, description="Return only core fields for each project.")


class CreateProjectParams(ActionParams):
    name: str | None = Field(default=None, min_length=1, description="Project name.")
    path: str | None = Field(default=None, min_length=1, description="Project path (URL slug).")
    namespace: NamespaceRef | None = Field(
        default=None, description="Owning group or user namespace; defaults to the caller's own."
    )
    description: str | None = Field(default=None, description="Project description.")
    visibility: Visibility | None = Field(default=None, description="Visibility level.")
    initialize_with_readme: bool = Field(
        default=False,
        description="Create an initial commit with a README, giving the repo a branch.",
    )
    default_branch: str | None = Field(
        default=None, min_length=1, description="Default branch name."
    )

    @model_validator(mode="after")
    def _name_or_path(self) -> "CreateProjectParams":
        if not (self.name or self.path):
            raise ValueError("Provide 'name', 'path', or both.")
        return self


class UpdateProjectParams(ActionParams):
    project: ProjectRef
    name: str | None = Field(default=None, min_length=1, description="Project name.")
    path: str | None = Field(default=None, min_length=1, description="Project path (URL slug).")
    description: str | None = Field(default=None, description="Project description.")
    visibility: Visibility | None = Field(default=None, description="Visibility level.")
    default_branch: str | None = Field(
        default=None, min_length=1, description="Default branch name."
    )
    merge_method: Literal["merge", "rebase_merge", "ff"] | None = Field(
        default=None, description="How merge requests are merged."
    )
    topics: list[str] | None = Field(default=None, description="Replaces the project's topics.")

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateProjectParams":
        if not query(self):
            raise ValueError("Nothing to update: set at least one project field.")
        return self


class ForkProjectParams(ActionParams):
    project: ProjectRef
    namespace: NamespaceRef | None = Field(
        default=None, description="Owning group or user namespace; defaults to the caller's own."
    )
    name: str | None = Field(default=None, min_length=1, description="Project name.")
    path: str | None = Field(default=None, min_length=1, description="Project path (URL slug).")
    description: str | None = Field(default=None, description="Project description.")
    visibility: Visibility | None = Field(default=None, description="Visibility level.")


async def list_projects(params: ListProjectsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page("/projects", params=query(params))


async def get_project(params: ProjectParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(project_path(params.project))


async def create_project(params: CreateProjectParams, ctx: ActionContext) -> Any:
    body = query(params, "namespace")
    if params.namespace is not None:
        body["namespace_id"] = await _namespace_id(params.namespace, ctx)
    return await ctx.gitlab.post("/projects", json_body=body)


async def update_project(params: UpdateProjectParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(project_path(params.project), json_body=query(params))


async def delete_project(params: ProjectParams, ctx: ActionContext) -> Any:
    response = await ctx.gitlab.delete(project_path(params.project))
    result: dict[str, Any] = {"gitlab_response": response}
    # PRD-01 section 4: surface GitLab's soft-delete retention, which only a read-back shows.
    try:
        project = await ctx.gitlab.get(project_path(params.project))
    except GitLabNotFoundError:
        return {
            **result,
            "status": "deleted",
            "note": "GitLab no longer returns the project: it was deleted without a retention "
            "period and cannot be restored.",
        }
    except GitLabError:
        project = None
    marked_on = project.get("marked_for_deletion_on") if isinstance(project, dict) else None
    if marked_on:
        return {
            **result,
            "status": "marked_for_deletion",
            "marked_for_deletion_on": marked_on,
            "note": f"GitLab keeps the project until {marked_on}, when it is permanently "
            "deleted. Until then an Owner can restore it.",
        }
    return {
        **result,
        "status": "deletion_requested",
        "note": "GitLab deletes projects asynchronously; it did not report a retention date.",
    }


async def fork_project(params: ForkProjectParams, ctx: ActionContext) -> Any:
    body = query(params, "namespace")
    namespace = params.namespace
    if isinstance(namespace, int) or (isinstance(namespace, str) and namespace.isdigit()):
        body["namespace_id"] = int(namespace)
    elif namespace:
        body["namespace_path"] = namespace
    return await ctx.gitlab.post(f"{project_path(params.project)}/fork", json_body=body)


async def archive_project(params: ProjectParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{project_path(params.project)}/archive")


async def unarchive_project(params: ProjectParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{project_path(params.project)}/unarchive")


async def star_project(params: ProjectParams, ctx: ActionContext) -> Any:
    # GitLab answers 304 with no body when the project was already starred.
    response = await ctx.gitlab.post(f"{project_path(params.project)}/star")
    return {"starred": True, "changed": response is not None}


async def unstar_project(params: ProjectParams, ctx: ActionContext) -> Any:
    response = await ctx.gitlab.post(f"{project_path(params.project)}/unstar")
    return {"starred": False, "changed": response is not None}


async def list_forks(params: ListForksParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(f"{project_path(params.project)}/forks", params=query(params))


async def _namespace_id(namespace: int | str, ctx: ActionContext) -> int:
    if isinstance(namespace, int):
        return namespace
    if namespace.isdigit():
        return int(namespace)
    found = await ctx.gitlab.get(f"/namespaces/{encode_segment(namespace)}")
    return int(found["id"])


PROJECTS_TOOL = Tool(
    name="gitlab_projects",
    title="GitLab projects",
    description="Find, create, and manage GitLab projects (repositories).",
    actions=(
        Action(
            "list",
            "List projects visible to the caller.",
            ListProjectsParams,
            list_projects,
            Access.READ,
        ),
        Action("get", "Get one project's details.", ProjectParams, get_project, Access.READ),
        Action(
            "create",
            "Create a project (repository).",
            CreateProjectParams,
            create_project,
            Access.WRITE,
        ),
        Action(
            "update", "Change project settings.", UpdateProjectParams, update_project, Access.WRITE
        ),
        Action(
            "delete",
            "Delete a project and its repository.",
            ProjectParams,
            delete_project,
            Access.WRITE,
            destructive=True,
        ),
        Action(
            "fork",
            "Fork a project into a namespace.",
            ForkProjectParams,
            fork_project,
            Access.WRITE,
        ),
        Action(
            "archive",
            "Archive a project (read-only).",
            ProjectParams,
            archive_project,
            Access.WRITE,
        ),
        Action("unarchive", "Unarchive a project.", ProjectParams, unarchive_project, Access.WRITE),
        Action("star", "Star a project.", ProjectParams, star_project, Access.WRITE),
        Action("unstar", "Unstar a project.", ProjectParams, unstar_project, Access.WRITE),
        Action("list_forks", "List a project's forks.", ListForksParams, list_forks, Access.READ),
    ),
)
