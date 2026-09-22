"""Two callers build repositories at once via the real toolsets, each with only their own PAT."""

import json
import random
from typing import Any
from urllib.parse import unquote

import anyio
import httpx
from mcp.client.session import ClientSession

from mcp_gitlab.toolsets import TOOLSETS
from tests.transport.harness import build_app, client_session, running

USERS = ("alice", "bob")
NAMESPACE_IDS = {"alice-group": 11, "bob-group": 12}
PROJECT_IDS = {11: 101, 12: 102}
SCOPE_LOOKUP = ("GET", "/personal_access_tokens/self")


def pat(user: str) -> str:
    return f"glpat-{user}-" + "x" * 16


class RecordingGitLab(httpx.MockTransport):
    """Just enough of GitLab to create a repository; records the PAT on every request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        super().__init__(self._handle)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        await anyio.sleep(random.uniform(0, 0.005))  # interleave the two callers
        path = request.url.raw_path.decode().split("?", 1)[0].removeprefix("/api/v4")
        self.calls.append((request.method, path, request.headers.get("authorization")))
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if (request.method, path) == SCOPE_LOOKUP:
            return httpx.Response(200, json={"scopes": ["api"]})
        if request.method == "GET" and path.startswith("/namespaces/"):
            return httpx.Response(200, json={"id": NAMESPACE_IDS[unquote(path[12:])]})
        if (request.method, path) == ("POST", "/projects"):
            project_id = PROJECT_IDS[body["namespace_id"]]
            return httpx.Response(201, json={"id": project_id, "default_branch": "main"})
        if request.method == "POST":
            return httpx.Response(201, json={"created": path, **body})
        return httpx.Response(404, json={"message": "404 Not Found"})


def expected_calls(user: str) -> list[tuple[str, str]]:
    project = f"/projects/{PROJECT_IDS[NAMESPACE_IDS[f'{user}-group']]}"
    return [
        ("GET", f"/namespaces/{user}-group"),
        ("POST", "/projects"),
        ("POST", f"{project}/repository/branches"),
        ("POST", f"{project}/repository/files/docs%2F.gitkeep"),
        ("POST", f"{project}/repository/files/docs%2FREADME.md"),
        ("POST", f"{project}/repository/commits"),
    ]


async def call(session: ClientSession, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(tool, arguments)
    assert result.is_error is False, result.structured_content
    assert result.structured_content is not None
    return result.structured_content


async def build_repository(session: ClientSession, user: str) -> None:
    project = await call(
        session,
        "gitlab_projects",
        {
            "action": "create",
            "name": "app",
            "namespace": f"{user}-group",
            "initialize_with_readme": True,
        },
    )
    target = {"project": project["id"], "branch": "feature/docs"}
    await call(session, "gitlab_branches", {"action": "create", **target, "ref": "main"})
    directory = await call(
        session,
        "gitlab_files",
        {
            "action": "create_directory",
            **target,
            "directory": "docs",
            "commit_message": "Add docs directory",
        },
    )
    assert directory["placeholder_file"] == "docs/.gitkeep"
    await call(
        session,
        "gitlab_files",
        {
            "action": "create",
            **target,
            "file_path": "docs/README.md",
            "content": "# Docs\n",
            "commit_message": "Add docs README",
        },
    )
    await call(
        session,
        "gitlab_commits",
        {
            "action": "batch_commit",
            **target,
            "commit_message": "Add src package",
            "actions": [
                {"action": "create", "file_path": "src/__init__.py", "content": ""},
                {"action": "create", "file_path": "src/main.py", "content": "print('hi')\n"},
            ],
        },
    )


async def test_write_tools_are_listed_for_a_caller_with_api_scope() -> None:
    gitlab = RecordingGitLab()
    app = build_app(gitlab, toolsets=TOOLSETS)
    async with running(app), client_session(app, {"Authorization": f"Bearer {pat('alice')}"}) as s:
        listed = await s.list_tools()
    actions = {
        tool.name: tool.input_schema["properties"]["action"]["enum"] for tool in listed.tools
    }
    assert set(actions) == {
        "gitlab_projects",
        "gitlab_branches",
        "gitlab_tags",
        "gitlab_repository_tree",
        "gitlab_files",
        "gitlab_commits",
    }
    assert "create" in actions["gitlab_projects"]
    assert "create" in actions["gitlab_branches"]
    assert {"create", "create_directory", "update", "delete"} <= set(actions["gitlab_files"])
    assert "batch_commit" in actions["gitlab_commits"]
    assert {auth for _, _, auth in gitlab.calls} == {f"Bearer {pat('alice')}"}


async def test_concurrent_callers_create_repositories_with_only_their_own_pat() -> None:
    gitlab = RecordingGitLab()
    app = build_app(gitlab, toolsets=TOOLSETS)

    async def act_as(user: str) -> None:
        async with client_session(app, {"Authorization": f"Bearer {pat(user)}"}) as session:
            await build_repository(session, user)

    async with running(app), anyio.create_task_group() as group:
        for user in USERS:
            group.start_soon(act_as, user)

    for user in USERS:
        carried_this_pat = [
            (method, path)
            for method, path, auth in gitlab.calls
            if auth == f"Bearer {pat(user)}" and (method, path) != SCOPE_LOOKUP
        ]
        assert carried_this_pat == expected_calls(user)
    assert all(auth in {f"Bearer {pat(user)}" for user in USERS} for _, _, auth in gitlab.calls)
