import httpx

from mcp_gitlab.config import Settings
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.gitlab.scopes import resolve_token_scopes
from tests.support import GitLabStub, RecordingSleep, StubResponse


def session(stub: GitLabStub):  # type: ignore[no-untyped-def]
    return GitLabClient(Settings(), transport=stub.transport(), sleep=RecordingSleep()).session(
        "glpat-x"
    )


async def test_returns_token_scopes() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/personal_access_tokens/self",
        StubResponse(json={"scopes": ["read_api", "read_repository"]}),
    )
    assert await resolve_token_scopes(session(stub)) == frozenset({"read_api", "read_repository"})


async def test_unknown_when_endpoint_missing() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/personal_access_tokens/self",
        StubResponse(status=404, json={"message": "404 Not Found"}),
    )
    assert await resolve_token_scopes(session(stub)) is None


async def test_unknown_when_gitlab_unreachable() -> None:
    stub = GitLabStub()
    stub.add("GET", "/personal_access_tokens/self", httpx.ConnectError)
    assert await resolve_token_scopes(session(stub)) is None


async def test_unknown_when_payload_unexpected() -> None:
    stub = GitLabStub()
    stub.add("GET", "/personal_access_tokens/self", StubResponse(json={"scopes": "api"}))
    assert await resolve_token_scopes(session(stub)) is None
