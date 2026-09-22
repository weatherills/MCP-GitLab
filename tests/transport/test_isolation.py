"""The server is shared: each request must carry its caller's PAT, used for that request only."""

import random
from collections import Counter

import anyio
import httpx
import pytest

from mcp_gitlab.config import Settings
from tests.transport.harness import (
    MCP_HEADERS,
    build_app,
    client_session,
    http_client,
    jsonrpc_message,
    running,
)

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "isolation-test", "version": "0"},
    },
}
GET_WIDGET = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "fake_widgets",
        "arguments": {"action": "get", "project": "1", "widget": "w"},
    },
}


def pat(user: str) -> str:
    return f"glpat-{user}-" + "x" * 16


def bearer(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pat(user)}"}


class EchoGitLab(httpx.MockTransport):
    """Answers every call with the Authorization header it arrived with, and records it."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None]] = []
        super().__init__(self._echo)

    async def _echo(self, request: httpx.Request) -> httpx.Response:
        await anyio.sleep(random.uniform(0, 0.005))  # interleave concurrent callers
        authorization = request.headers.get("authorization")
        self.seen.append((request.url.path, authorization))
        if request.url.path.endswith("/personal_access_tokens/self"):
            return httpx.Response(200, json={"scopes": ["api"]})
        return httpx.Response(200, json={"name": authorization})


async def test_concurrent_callers_each_reach_gitlab_with_their_own_pat() -> None:
    gitlab = EchoGitLab()
    app = build_app(gitlab)
    users = [f"user{i}" for i in range(12)]
    answered: dict[str, list[object]] = {}

    async def act_as(user: str) -> None:
        async with client_session(app, bearer(user)) as session:
            for _ in range(3):
                result = await session.call_tool(
                    "fake_widgets", {"action": "get", "project": "1", "widget": "w"}
                )
                assert result.structured_content is not None
                answered.setdefault(user, []).append(result.structured_content["name"])

    async with running(app):
        async with anyio.create_task_group() as group:
            for user in users:
                group.start_soon(act_as, user)

    assert answered == {user: [f"Bearer {pat(user)}"] * 3 for user in users}
    widget_calls = Counter(auth for path, auth in gitlab.seen if path.endswith("/widgets/w"))
    assert widget_calls == {f"Bearer {pat(user)}": 3 for user in users}
    # Scope lookups for tools/list included: no call ever went out without, or with a foreign, PAT.
    assert {auth for _, auth in gitlab.seen} == {f"Bearer {pat(user)}" for user in users}


async def test_tool_list_scope_lookup_uses_each_callers_own_pat() -> None:
    gitlab = EchoGitLab()
    app = build_app(gitlab)

    async def list_as(user: str) -> None:
        async with client_session(app, bearer(user)) as session:
            await session.list_tools()

    async with running(app):
        async with anyio.create_task_group() as group:
            for user in ("alice", "bob", "carol"):
                group.start_soon(list_as, user)

    assert sorted(auth or "" for _, auth in gitlab.seen) == sorted(
        f"Bearer {pat(user)}" for user in ("alice", "bob", "carol")
    )


async def test_a_stateful_session_never_carries_a_pat_to_another_request() -> None:
    gitlab = EchoGitLab()
    app = build_app(gitlab, Settings(mcp_stateless_http=False))
    async with http_client(app) as client:
        opened = await client.post(
            "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **bearer("alice")}
        )
        session = {
            **MCP_HEADERS,
            "mcp-session-id": opened.headers["mcp-session-id"],
            "mcp-protocol-version": "2025-11-25",
        }
        await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**session, **bearer("alice")},
        )
        as_bob = await client.post("/mcp", json=GET_WIDGET, headers={**session, **bearer("bob")})
        without_pat = await client.post("/mcp", json=GET_WIDGET, headers=session)

    assert jsonrpc_message(as_bob)["result"]["structuredContent"] == {
        "name": f"Bearer {pat('bob')}"
    }
    assert without_pat.status_code == 401
    assert gitlab.seen == [("/api/v4/projects/1/widgets/w", f"Bearer {pat('bob')}")]


@pytest.mark.parametrize(
    ("method", "body"),
    [
        ("POST", INITIALIZE),
        ("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"}),
        ("GET", None),
        ("DELETE", None),
    ],
)
async def test_every_mcp_request_requires_a_pat(method: str, body: object) -> None:
    async with http_client(build_app(EchoGitLab())) as client:
        response = await client.request(method, "/mcp", json=body, headers=MCP_HEADERS)
    assert response.status_code == 401


async def test_gitlab_token_environment_variable_is_never_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", pat("server"))
    gitlab = EchoGitLab()
    async with http_client(build_app(gitlab)) as client:
        initialize = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        call = await client.post("/mcp", json=GET_WIDGET, headers=MCP_HEADERS)
    assert (initialize.status_code, call.status_code) == (401, 401)
    assert gitlab.seen == []
