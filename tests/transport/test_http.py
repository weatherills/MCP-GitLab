import anyio
import httpx

from mcp_gitlab import __version__
from mcp_gitlab.app import create_app
from mcp_gitlab.config import Settings
from tests.support import GitLabStub
from tests.transport.harness import AUTH, build_app, http_client

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def test_health_needs_no_credentials() -> None:
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_mcp_rejects_anonymous_requests() -> None:
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["error"]["code"] == "authentication_required"


async def test_mcp_rejects_foreign_browser_origins() -> None:
    headers = {**MCP_HEADERS, **AUTH, "Origin": "http://evil.example"}
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 403


async def test_mcp_rejects_unexpected_host_headers() -> None:
    async with http_client(
        build_app(GitLabStub()), base_url="http://rebound.example:8080"
    ) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **AUTH})
    assert response.status_code == 421


async def test_authenticated_initialize_succeeds() -> None:
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **AUTH})
    assert response.status_code == 200
    assert "mcp-gitlab" in response.text


async def test_stateless_mode_refuses_the_standalone_get_stream() -> None:
    headers = {**AUTH, "Accept": "text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    async with http_client(build_app(GitLabStub())) as client:
        with anyio.fail_after(5):  # without the guard the SDK holds an idle SSE stream open
            response = await client.get("/mcp", headers=headers)
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert response.json()["error"]["code"] == -32600


async def test_stateful_mode_leaves_get_to_the_session_manager() -> None:
    headers = {**AUTH, "Accept": "text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    app = build_app(GitLabStub(), Settings(mcp_stateless_http=False))
    async with http_client(app) as client:
        response = await client.get("/mcp", headers=headers)  # no MCP-Session-Id yet
    assert response.status_code == 400


class _TrackingTransport(httpx.MockTransport):
    closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_gitlab_connection_pool_closes_on_shutdown() -> None:
    transport = _TrackingTransport(GitLabStub()._handle)
    app = create_app(Settings(), toolsets=(), gitlab_transport=transport)
    async with http_client(app) as client:
        await client.get("/healthz")
        assert transport.closed is False
    assert transport.closed is True
