"""PRD-02 toolset `repository`: gitlab_repository_tree, gitlab_files, gitlab_commits."""

import base64

import pytest

from mcp_gitlab.config import Settings
from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, call, dispatcher

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
FILE = f"{P}/repository/files/src%2Fapp.py"
COMMIT = {"branch": "main", "commit_message": "Change app"}


def file_payload(content: bytes, size: int | None = None) -> dict[str, object]:
    return {
        "file_name": "app.py",
        "file_path": "src/app.py",
        "size": len(content) if size is None else size,
        "encoding": "base64",
        "content": base64.b64encode(content).decode(),
        "ref": "main",
        "blob_id": "b1",
        "commit_id": "c1",
        "last_commit_id": "lc1",
        "execute_filemode": False,
    }


CASES = [
    Case(
        "gitlab_repository_tree",
        {"action": "list", "project": "grp/app", "path": "src", "ref": "main", "recursive": True},
        "GET",
        f"{P}/repository/tree",
        {"page": "1", "per_page": "20", "path": "src", "ref": "main", "recursive": "true"},
        response=LIST,
    ),
    Case(
        "gitlab_files",
        {"action": "get", "project": "grp/app", "file_path": "src/app.py"},
        "GET",
        FILE,
        {"ref": "HEAD"},
        response=StubResponse(json=file_payload(b"print('hi')\n")),
    ),
    Case(
        "gitlab_files",
        {"action": "get_raw", "project": "grp/app", "file_path": "src/app.py", "ref": "main"},
        "GET",
        f"{FILE}/raw",
        {"ref": "main"},
        response=StubResponse(content=b"print('hi')\n"),
    ),
    Case(
        "gitlab_files",
        {
            "action": "get_blame",
            "project": "grp/app",
            "file_path": "src/app.py",
            "range_start": 1,
            "range_end": 5,
        },
        "GET",
        f"{FILE}/blame",
        {"ref": "HEAD", "range[start]": "1", "range[end]": "5"},
        response=LIST,
    ),
    Case(
        "gitlab_files",
        {
            "action": "create",
            "project": "grp/app",
            "file_path": "src/app.py",
            "content": "print('hi')\n",
            "start_branch": "main",
            **COMMIT,
            "branch": "feature/app",
        },
        "POST",
        FILE,
        body={
            "branch": "feature/app",
            "commit_message": "Change app",
            "start_branch": "main",
            "content": "print('hi')\n",
            "encoding": "text",
        },
        response=StubResponse(
            status=201, json={"file_path": "src/app.py", "branch": "feature/app"}
        ),
    ),
    Case(
        "gitlab_files",
        {
            "action": "update",
            "project": "grp/app",
            "file_path": "src/app.py",
            "content": "cHJpbnQoKQo=",
            "encoding": "base64",
            "last_commit_id": "lc1",
            **COMMIT,
        },
        "PUT",
        FILE,
        body={**COMMIT, "content": "cHJpbnQoKQo=", "encoding": "base64", "last_commit_id": "lc1"},
    ),
    Case(
        "gitlab_files",
        {
            "action": "delete",
            "project": "grp/app",
            "file_path": "src/app.py",
            "last_commit_id": "lc1",
            **COMMIT,
        },
        "DELETE",
        FILE,
        {**COMMIT, "last_commit_id": "lc1"},
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_files",
        {
            "action": "create_directory",
            "project": "grp/app",
            "directory": "/docs/guides/",
            **COMMIT,
        },
        "POST",
        f"{P}/repository/files/docs%2Fguides%2F.gitkeep",
        body={**COMMIT, "content": "", "encoding": "text"},
        response=StubResponse(status=201, json={"file_path": "docs/guides/.gitkeep"}),
    ),
    Case(
        "gitlab_commits",
        {"action": "list", "project": "grp/app", "ref_name": "main", "path": "src"},
        "GET",
        f"{P}/repository/commits",
        {"page": "1", "per_page": "20", "ref_name": "main", "path": "src"},
        response=LIST,
    ),
    Case(
        "gitlab_commits",
        {"action": "get", "project": "grp/app", "sha": "abc123"},
        "GET",
        f"{P}/repository/commits/abc123",
    ),
    Case(
        "gitlab_commits",
        {"action": "get_diff", "project": "grp/app", "sha": "abc123"},
        "GET",
        f"{P}/repository/commits/abc123/diff",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_commits",
        {"action": "compare", "project": "grp/app", "from_ref": "main", "to_ref": "feature/app"},
        "GET",
        f"{P}/repository/compare",
        {"from": "main", "to": "feature/app", "straight": "false"},
    ),
    Case(
        "gitlab_commits",
        {
            "action": "batch_commit",
            "project": "grp/app",
            **COMMIT,
            "actions": [
                {"action": "create", "file_path": "a.txt", "content": "A"},
                {"action": "delete", "file_path": "b.txt"},
                {"action": "move", "file_path": "c2.txt", "previous_path": "c.txt"},
            ],
        },
        "POST",
        f"{P}/repository/commits",
        body={
            **COMMIT,
            "actions": [
                {"action": "create", "file_path": "a.txt", "content": "A", "encoding": "text"},
                {"action": "delete", "file_path": "b.txt", "encoding": "text"},
                {
                    "action": "move",
                    "file_path": "c2.txt",
                    "previous_path": "c.txt",
                    "encoding": "text",
                },
            ],
        },
        response=StubResponse(status=201, json={"id": "new-sha"}),
    ),
    Case(
        "gitlab_commits",
        {"action": "cherry_pick", "project": "grp/app", "sha": "abc123", "branch": "stable"},
        "POST",
        f"{P}/repository/commits/abc123/cherry_pick",
        body={"branch": "stable", "dry_run": False},
    ),
    Case(
        "gitlab_commits",
        {
            "action": "revert",
            "project": "grp/app",
            "sha": "abc123",
            "branch": "main",
            "dry_run": True,
        },
        "POST",
        f"{P}/repository/commits/abc123/revert",
        body={"branch": "main", "dry_run": True},
    ),
    Case(
        "gitlab_commits",
        {"action": "list_statuses", "project": "grp/app", "sha": "abc123", "ref": "main"},
        "GET",
        f"{P}/repository/commits/abc123/statuses",
        {"page": "1", "per_page": "20", "ref": "main"},
        response=LIST,
    ),
    Case(
        "gitlab_commits",
        {"action": "list_comments", "project": "grp/app", "sha": "abc123"},
        "GET",
        f"{P}/repository/commits/abc123/comments",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_commits",
        {
            "action": "create_comment",
            "project": "grp/app",
            "sha": "abc123",
            "note": "Nice",
            "file_path": "src/app.py",
            "line": 3,
            "line_type": "new",
        },
        "POST",
        f"{P}/repository/commits/abc123/comments",
        body={"note": "Nice", "path": "src/app.py", "line": 3, "line_type": "new"},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


def test_every_prd02_action_is_covered() -> None:
    from mcp_gitlab.toolsets.repository import TOOLSET

    declared = {f"{tool.name}.{action.name}" for tool in TOOLSET.tools for action in tool.actions}
    assert declared == {case.id for case in CASES}


async def test_get_returns_text_content_with_metadata() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/1/repository/files/src%2Fapp.py",
        StubResponse(json=file_payload(b"x = 1\n")),
    )
    outcome = await call(
        stub, "gitlab_files", {"action": "get", "project": 1, "file_path": "src/app.py"}
    )
    assert outcome.structured["encoding"] == "text"
    assert outcome.structured["content"] == "x = 1\n"
    assert outcome.structured["last_commit_id"] == "lc1"


async def test_binary_content_stays_base64() -> None:
    blob = b"\x89PNG\r\n\x1a\n\x00\xff"
    stub = GitLabStub()
    stub.add("GET", "/projects/1/repository/files/logo.png/raw", StubResponse(content=blob))
    outcome = await call(
        stub, "gitlab_files", {"action": "get_raw", "project": 1, "file_path": "logo.png"}
    )
    assert outcome.structured["encoding"] == "base64"
    assert base64.b64decode(outcome.structured["content"]) == blob


async def test_oversized_file_is_refused_by_reported_size() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/1/repository/files/big.bin",
        StubResponse(json=file_payload(b"x", size=5000)),
    )
    outcome = await call(
        stub,
        "gitlab_files",
        {"action": "get", "project": 1, "file_path": "big.bin"},
        Settings(gitlab_mcp_max_file_bytes=1000),
    )
    error = outcome.structured["error"]
    assert error["code"] == "payload_too_large"
    assert error["details"] == {"max_bytes": 1000, "size": 5000}
    assert "get_blame" in error["message"]


async def test_oversized_raw_file_is_refused_while_streaming() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/1/repository/files/big.bin/raw", StubResponse(content=b"x" * 2000))
    outcome = await call(
        stub,
        "gitlab_files",
        {"action": "get_raw", "project": 1, "file_path": "big.bin"},
        Settings(gitlab_mcp_max_file_bytes=1000),
    )
    assert outcome.structured["error"]["code"] == "payload_too_large"
    assert "GITLAB_MCP_MAX_FILE_BYTES" in outcome.structured["error"]["message"]


async def test_create_directory_reports_the_placeholder() -> None:
    stub = GitLabStub()
    stub.add(
        "POST", "/projects/1/repository/files/docs%2F.gitkeep", StubResponse(status=201, json={})
    )
    outcome = await call(
        stub,
        "gitlab_files",
        {"action": "create_directory", "project": 1, "directory": "docs", **COMMIT},
    )
    assert outcome.structured["directory"] == "docs"
    assert outcome.structured["placeholder_file"] == "docs/.gitkeep"


async def test_create_directory_rejects_the_root() -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_files",
        {"action": "create_directory", "project": 1, "directory": "/", **COMMIT},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_changes_to_existing_files_need_last_commit_id(action: str) -> None:
    arguments = {"action": action, "project": 1, "file_path": "a.txt", "content": "x", **COMMIT}
    if action == "delete":
        del arguments["content"]
    outcome = await call(GitLabStub(), "gitlab_files", arguments)
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_blame_range_must_be_complete() -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_files",
        {"action": "get_blame", "project": 1, "file_path": "a.txt", "range_start": 4},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "bad_action",
    [
        {"action": "create", "file_path": "a.txt"},
        {"action": "move", "file_path": "b.txt"},
        {"action": "chmod", "file_path": "c.sh"},
        {"action": "rename", "file_path": "d.txt"},
    ],
)
async def test_batch_commit_validates_each_action(bad_action: dict[str, str]) -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_commits",
        {"action": "batch_commit", "project": 1, **COMMIT, "actions": [bad_action]},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_diff_is_summarized_with_full_text_only_on_request() -> None:
    diffs = [
        {"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1,2 +1,3 @@\n x\n-y\n+z\n+w\n"},
        {
            "old_path": "b.py",
            "new_path": "b.py",
            "diff": "@@ -1 +1 @@\n-old\n+new\n",
            "new_file": False,
        },
    ]
    stub = GitLabStub()
    stub.add("GET", "/projects/1/repository/commits/abc/diff", StubResponse(json=diffs))
    outcome = await call(
        stub,
        "gitlab_commits",
        {"action": "get_diff", "project": 1, "sha": "abc", "include_diff_for": ["b.py"]},
    )
    first, second = outcome.structured["items"]
    assert (first["additions"], first["deletions"], "diff" in first) == (2, 1, False)
    assert (second["additions"], second["deletions"], second["diff"]) == (1, 1, diffs[1]["diff"])


async def test_compare_summarizes_commits_and_diffs() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/1/repository/compare",
        StubResponse(
            json={
                "commits": [
                    {
                        "id": "c1",
                        "short_id": "c1",
                        "title": "Add",
                        "author_name": "A",
                        "message": "long",
                    }
                ],
                "diffs": [{"old_path": "a", "new_path": "a", "diff": "+x\n"}],
                "compare_timeout": False,
                "compare_same_ref": False,
            }
        ),
    )
    outcome = await call(
        stub,
        "gitlab_commits",
        {"action": "compare", "project": 1, "from_ref": "main", "to_ref": "dev"},
    )
    assert outcome.structured["commits"] == [
        {"id": "c1", "short_id": "c1", "title": "Add", "author_name": "A", "authored_date": None}
    ]
    assert outcome.structured["diffs"][0]["additions"] == 1
    assert "diff" not in outcome.structured["diffs"][0]


async def test_file_writes_are_hidden_and_blocked_in_read_only_mode() -> None:
    from mcp_gitlab.tools.registry import ToolRegistry
    from mcp_gitlab.toolsets import TOOLSETS
    from tests.fakes import request_context

    registry = ToolRegistry(TOOLSETS)
    views = {
        v.tool.name: [a.name for a in v.actions]
        for v in registry.visible(request_context(read_only=True), None)
    }
    assert views["gitlab_files"] == ["get", "get_raw", "get_blame"]
    assert views["gitlab_projects"] == ["list", "get", "list_forks"]

    stub = GitLabStub()
    outcome = await dispatcher(stub).call(
        "gitlab_files",
        {"action": "create", "project": 1, "file_path": "a.txt", "content": "x", **COMMIT},
        request_context(read_only=True),
    )
    assert outcome.structured["error"]["code"] == "read_only_mode"
    assert stub.requests == []
