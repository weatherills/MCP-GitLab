"""gitlab_snippets: code snippets, a project's or the caller's own (PRD-08 section 3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import PayloadTooLargeError
from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, Visibility, query
from mcp_gitlab.toolsets.content import file_too_large, present

SnippetId = Annotated[int, Field(ge=1, description="The snippet's ID, from list or create.")]
PROJECT_HELP = (
    "Project ID, or its full path such as group/subgroup/project, for a project's snippets. "
    "Leave out for personal snippets."
)
SNIPPET_FILE_HINT = "Open the snippet in GitLab, or read a smaller file from it."


class SnippetFile(ActionParams):
    """One file of a snippet: create takes file_path and content; update also takes action."""

    file_path: str = Field(min_length=1, description="The file's path in the snippet.")
    content: str | None = Field(
        default=None, description="The file's content; needed to add or change a file."
    )
    action: Literal["create", "update", "delete", "move"] | None = Field(
        default=None,
        description="For update: create, update, delete, or move this file. create ignores it.",
    )
    previous_path: str | None = Field(
        default=None, min_length=1, description="For a move: the file's current path."
    )


Files = Annotated[
    list[SnippetFile] | None,
    Field(
        default=None,
        min_length=1,
        description="The snippet's files, for a snippet with several: instead of content and "
        "file_name.",
    ),
]
Content = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="The content of a one-file snippet, with file_name; files is for several.",
    ),
]
FileName = Annotated[
    str | None, Field(default=None, min_length=1, description="The file name, with content.")
]
SnippetVisibility = Annotated[
    Visibility | None,
    Field(
        default=None,
        description="Who can see the snippet: private, internal, or public. create makes it "
        "private unless this says otherwise.",
    ),
]


class SnippetOwner(ActionParams):
    project: ProjectRef | None = Field(default=None, description=PROJECT_HELP)

    def snippets_path(self) -> str:
        return f"{project_path(self.project)}/snippets" if self.project is not None else "/snippets"


class ListSnippetsParams(SnippetOwner, PageParams):
    scope: Literal["mine", "public", "all"] | None = Field(
        default=None,
        description="For personal snippets: mine (the default), every public snippet, or all "
        "the snippets you can see (GitLab 16.3 and later). Not with project.",
    )

    @model_validator(mode="after")
    def _scope_is_personal(self) -> "ListSnippetsParams":
        if self.scope is not None and self.project is not None:
            raise ValueError("scope lists personal snippets: leave out project.")
        return self


class SnippetParams(SnippetOwner):
    snippet_id: SnippetId

    def snippet_path(self) -> str:
        return f"{self.snippets_path()}/{self.snippet_id}"


class GetContentParams(SnippetParams):
    file_path: str | None = Field(
        default=None,
        min_length=1,
        description="The file to read, for a snippet with several files; the first file if "
        "left out.",
    )
    ref: str = Field(
        default="HEAD",
        min_length=1,
        description="Branch, tag, or commit of the snippet's repository; HEAD is its latest "
        "version.",
    )


class CreateSnippetParams(SnippetOwner):
    title: str = Field(min_length=1, description="Snippet title.")
    description: str | None = Field(default=None, description="Snippet description.")
    visibility: SnippetVisibility
    content: Content
    file_name: FileName
    files: Files

    @model_validator(mode="after")
    def _content_or_files(self) -> "CreateSnippetParams":
        if (self.content is None) == (self.files is None):
            raise ValueError("Give content with file_name, or files, but not both.")
        if self.content is not None and self.file_name is None:
            raise ValueError("content needs file_name.")
        if self.files is not None:
            if self.file_name is not None:
                raise ValueError("file_name goes with content; with files, give each file_path.")
            if any(file.content is None for file in self.files):
                raise ValueError("Each new file needs content.")
            if any(file.action not in (None, "create") for file in self.files):
                raise ValueError("A new snippet's files can only be created.")
        return self


class UpdateSnippetParams(SnippetParams):
    title: str | None = Field(default=None, min_length=1, description="Snippet title.")
    description: str | None = Field(default=None, description="Snippet description.")
    visibility: SnippetVisibility
    content: Content
    file_name: FileName
    files: Files

    @model_validator(mode="after")
    def _valid_changes(self) -> "UpdateSnippetParams":
        if not query(self, "snippet_id"):
            raise ValueError("Nothing to update: set a field, content, or files.")
        if self.files is not None:
            if self.content is not None or self.file_name is not None:
                raise ValueError("Give content and file_name, or files, not both.")
            for file in self.files:
                if file.action is None:
                    raise ValueError(f"Say what to do with '{file.file_path}': set its action.")
                if file.action == "move" and file.previous_path is None:
                    raise ValueError(f"Moving '{file.file_path}' needs its previous_path.")
        return self


async def list_snippets(params: ListSnippetsParams, ctx: ActionContext) -> Page:
    path = params.snippets_path()
    if params.scope in ("public", "all"):
        path = f"{path}/{params.scope}"
    return await ctx.gitlab.get_page(path, params=params.page_query())


async def get_snippet(params: SnippetParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(params.snippet_path())


async def get_content(params: GetContentParams, ctx: ActionContext) -> Any:
    if params.file_path is None:
        path = f"{params.snippet_path()}/raw"
    else:
        path = (
            f"{params.snippet_path()}/files/{encode_segment(params.ref)}/"
            f"{encode_segment(params.file_path)}/raw"
        )
    limit = ctx.settings.gitlab_mcp_max_file_bytes
    name = params.file_path or f"snippet {params.snippet_id}"
    try:
        data = await ctx.gitlab.get_bytes(path, max_bytes=limit)
    except PayloadTooLargeError as exc:
        raise file_too_large(name, limit, hint=SNIPPET_FILE_HINT) from exc
    return {"snippet_id": params.snippet_id, "file_path": params.file_path, **present(data)}


async def create_snippet(params: CreateSnippetParams, ctx: ActionContext) -> Any:
    # GitLab makes a personal snippet internal by default; private is the safer start.
    body = {"visibility": "private", **query(params, "files")}
    if params.files is not None:
        body["files"] = [{"file_path": f.file_path, "content": f.content} for f in params.files]
    return await ctx.gitlab.post(params.snippets_path(), json_body=body)


async def update_snippet(params: UpdateSnippetParams, ctx: ActionContext) -> Any:
    body = query(params, "snippet_id")
    return await ctx.gitlab.put(params.snippet_path(), json_body=body)


async def delete_snippet(params: SnippetParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(params.snippet_path())
    return {"deleted": params.snippet_id}


SNIPPETS_TOOL = Tool(
    name="gitlab_snippets",
    title="GitLab snippets",
    description=(
        "Share code as snippets: a project's (with project) or your own personal ones (without). "
        "List, read, create, change, and delete them. New snippets are private unless "
        "visibility says otherwise."
    ),
    actions=(
        Action(
            "list",
            "List a project's snippets, or personal ones: yours, public ones, or all you can see.",
            ListSnippetsParams,
            list_snippets,
            Access.READ,
        ),
        Action(
            "get",
            "Get a snippet's details and its list of files.",
            SnippetParams,
            get_snippet,
            Access.READ,
        ),
        Action(
            "get_content",
            "Read a snippet file's content: text, or base64 if it isn't UTF-8.",
            GetContentParams,
            get_content,
            Access.READ,
        ),
        Action(
            "create",
            "Create a snippet from content and file_name, or from files.",
            CreateSnippetParams,
            create_snippet,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a snippet's title, description, or visibility, or its files: content and "
            "file_name for a one-file snippet, files with an action each for several.",
            UpdateSnippetParams,
            update_snippet,
            Access.WRITE,
        ),
        Action("delete", "Delete a snippet.", SnippetParams, delete_snippet, Access.WRITE),
    ),
)
