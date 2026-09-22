"""gitlab_files: read and write repository files and create directories (PRD-02 section 3)."""

import base64
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from mcp_gitlab.core.errors import PayloadTooLargeError
from mcp_gitlab.gitlab import encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef
from mcp_gitlab.toolsets.content import file_too_large, present

# Git tracks files, not directories: a directory exists once it contains a file.
DIRECTORY_PLACEHOLDER = ".gitkeep"

FilePath = Annotated[
    str, Field(min_length=1, description="Path of the file in the repository, such as src/app.py.")
]
ReadRef = Annotated[
    str,
    Field(
        min_length=1, description="Branch, tag, or commit to read; HEAD means the default branch."
    ),
]
LastCommitId = Annotated[
    str,
    Field(
        min_length=1,
        description="The file's last_commit_id from a prior get; GitLab rejects the change if the "
        "file has changed since.",
    ),
]
Encoding = Literal["text", "base64"]


class FileParams(ActionParams):
    project: ProjectRef
    file_path: FilePath
    ref: ReadRef = "HEAD"


class BlameParams(FileParams):
    range_start: int | None = Field(default=None, ge=1, description="First line to blame.")
    range_end: int | None = Field(default=None, ge=1, description="Last line to blame.")

    @model_validator(mode="after")
    def _complete_range(self) -> "BlameParams":
        if (self.range_start is None) != (self.range_end is None):
            raise ValueError("Give both range_start and range_end, or neither.")
        if self.range_start is not None and self.range_end is not None:
            if self.range_start > self.range_end:
                raise ValueError("range_start must not be after range_end.")
        return self


class CommitOptions(ActionParams):
    project: ProjectRef
    branch: str = Field(
        min_length=1,
        description="Branch to commit to; created from start_branch when it does not exist yet.",
    )
    commit_message: str = Field(min_length=1, description="Commit message.")
    start_branch: str | None = Field(
        default=None, min_length=1, description="Existing branch to create a new branch from."
    )
    author_email: str | None = Field(default=None, description="Commit author email.")
    author_name: str | None = Field(default=None, description="Commit author name.")


class CreateFileParams(CommitOptions):
    file_path: FilePath
    content: str = Field(description="File content, as text or base64 according to encoding.")
    encoding: Encoding = Field(default="text", description="Use base64 for binary content.")
    execute_filemode: bool | None = Field(
        default=None, description="Set (true) or clear (false) the file's executable bit."
    )


class UpdateFileParams(CreateFileParams):
    last_commit_id: LastCommitId


class DeleteFileParams(CommitOptions):
    file_path: FilePath
    last_commit_id: LastCommitId


class CreateDirectoryParams(CommitOptions):
    directory: str = Field(min_length=1, description="Directory to create, such as docs/guides.")

    @field_validator("directory")
    @classmethod
    def _normalise(cls, value: str) -> str:
        directory = value.strip().strip("/")
        if not directory:
            raise ValueError("directory must name a path below the repository root.")
        return directory


async def get_file(params: FileParams, ctx: ActionContext) -> Any:
    limit = ctx.settings.gitlab_mcp_max_file_bytes
    try:
        # Content arrives base64-encoded inside JSON, so allow for that expansion here.
        data = await ctx.gitlab.get(
            _file_path(params.project, params.file_path),
            params={"ref": params.ref},
            max_bytes=limit * 2 + 64 * 1024,
        )
    except PayloadTooLargeError as exc:
        raise file_too_large(params.file_path, limit) from exc
    if int(data.get("size") or 0) > limit:
        raise file_too_large(params.file_path, limit, int(data["size"]))
    metadata = (
        "file_path",
        "size",
        "ref",
        "blob_id",
        "commit_id",
        "last_commit_id",
        "execute_filemode",
    )
    result = {key: data.get(key) for key in metadata}
    result.update(present(base64.b64decode(data.get("content") or "")))
    return result


async def get_raw_file(params: FileParams, ctx: ActionContext) -> Any:
    limit = ctx.settings.gitlab_mcp_max_file_bytes
    try:
        data = await ctx.gitlab.get_bytes(
            f"{_file_path(params.project, params.file_path)}/raw",
            params={"ref": params.ref},
            max_bytes=limit,
        )
    except PayloadTooLargeError as exc:
        raise file_too_large(params.file_path, limit) from exc
    return {"file_path": params.file_path, "ref": params.ref, "size": len(data), **present(data)}


async def get_blame(params: BlameParams, ctx: ActionContext) -> Any:
    query: dict[str, Any] = {"ref": params.ref}
    if params.range_start is not None:
        query["range[start]"] = params.range_start
        query["range[end]"] = params.range_end
    return await ctx.gitlab.get(
        f"{_file_path(params.project, params.file_path)}/blame", params=query
    )


async def create_file(params: CreateFileParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        _file_path(params.project, params.file_path), json_body=_content_body(params)
    )


async def update_file(params: UpdateFileParams, ctx: ActionContext) -> Any:
    body = {**_content_body(params), "last_commit_id": params.last_commit_id}
    return await ctx.gitlab.put(_file_path(params.project, params.file_path), json_body=body)


async def delete_file(params: DeleteFileParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(
        _file_path(params.project, params.file_path),
        params={**_commit_body(params), "last_commit_id": params.last_commit_id},
    )
    return {"deleted": params.file_path, "branch": params.branch}


async def create_directory(params: CreateDirectoryParams, ctx: ActionContext) -> Any:
    placeholder = f"{params.directory}/{DIRECTORY_PLACEHOLDER}"
    created = await ctx.gitlab.post(
        _file_path(params.project, placeholder),
        json_body={**_commit_body(params), "content": "", "encoding": "text"},
    )
    return {
        "directory": params.directory,
        "placeholder_file": placeholder,
        "branch": params.branch,
        "gitlab_response": created,
    }


def _file_path(project: int | str, file_path: str) -> str:
    return f"{project_path(project)}/repository/files/{encode_segment(file_path)}"


def _commit_body(params: CommitOptions) -> dict[str, Any]:
    fields = ("branch", "commit_message", "start_branch", "author_email", "author_name")
    return {key: getattr(params, key) for key in fields if getattr(params, key) is not None}


def _content_body(params: CreateFileParams) -> dict[str, Any]:
    body = {**_commit_body(params), "content": params.content, "encoding": params.encoding}
    if params.execute_filemode is not None:
        body["execute_filemode"] = params.execute_filemode
    return body


FILES_TOOL = Tool(
    name="gitlab_files",
    title="GitLab files",
    description=(
        "Read, create, update, and delete repository files, and create directories. Each change "
        "is one commit; use gitlab_commits batch_commit to change several files in one commit."
    ),
    actions=(
        Action(
            "get",
            "Read a file and its metadata (including last_commit_id).",
            FileParams,
            get_file,
            Access.READ,
        ),
        Action("get_raw", "Read a file's content only.", FileParams, get_raw_file, Access.READ),
        Action(
            "get_blame",
            "Show which commit last changed each line.",
            BlameParams,
            get_blame,
            Access.READ,
        ),
        Action(
            "create", "Create a file in a new commit.", CreateFileParams, create_file, Access.WRITE
        ),
        Action(
            "update",
            "Replace a file's content in a new commit.",
            UpdateFileParams,
            update_file,
            Access.WRITE,
        ),
        Action(
            "delete", "Delete a file in a new commit.", DeleteFileParams, delete_file, Access.WRITE
        ),
        Action(
            "create_directory",
            f"Create a directory by committing an empty {DIRECTORY_PLACEHOLDER} inside it (Git "
            "tracks files, not directories; creating a file under a path also creates it).",
            CreateDirectoryParams,
            create_directory,
            Access.WRITE,
        ),
    ),
)
