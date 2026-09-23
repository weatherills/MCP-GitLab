import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
import httpx
import pytest

from mcp_gitlab import __version__
from mcp_gitlab.app import create_app
from mcp_gitlab.config import Settings
from tests.support import GitLabStub
from tests.transport.harness import AUTH, build_app, http_client, jsonrpc_message

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
VERSION = {"MCP-Protocol-Version": "2025-11-25"}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
PING = {"jsonrpc": "2.0", "id": 2, "method": "ping"}


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


async def test_host_names_match_whatever_their_case() -> None:
    headers = {**MCP_HEADERS, **AUTH, "Host": "LocalHost:8080"}
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers=headers)
    assert response.status_code == 200


def _limited(max_bytes: int) -> Settings:
    return Settings(mcp_max_request_bytes=max_bytes)


async def test_a_body_over_the_limit_is_refused_with_413() -> None:
    body = json.dumps(INITIALIZE).encode()
    stub = GitLabStub()
    async with http_client(build_app(stub, _limited(len(body) - 1))) as client:
        response = await client.post("/mcp", content=body, headers={**MCP_HEADERS, **AUTH})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert stub.requests == []


async def test_a_body_without_a_length_is_counted_as_it_arrives() -> None:
    body = json.dumps(INITIALIZE).encode()

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 16):
            yield body[start : start + 16]

    async with http_client(build_app(GitLabStub(), _limited(len(body) - 1))) as client:
        response = await client.post("/mcp", content=chunks(), headers={**MCP_HEADERS, **AUTH})
    assert "content-length" not in response.request.headers
    assert response.status_code == 413


async def test_a_body_at_the_limit_is_served() -> None:
    body = json.dumps(INITIALIZE).encode()

    async def chunks() -> AsyncIterator[bytes]:
        yield body[:10]
        yield body[10:]

    async with http_client(build_app(GitLabStub(), _limited(len(body)))) as client:
        whole = await client.post("/mcp", content=body, headers={**MCP_HEADERS, **AUTH})
        chunked = await client.post("/mcp", content=chunks(), headers={**MCP_HEADERS, **AUTH})
    assert (whole.status_code, chunked.status_code) == (200, 200)
    assert "mcp-gitlab" in chunked.text


async def test_the_pat_is_checked_before_the_body_is_read() -> None:
    body = json.dumps(INITIALIZE).encode()
    async with http_client(build_app(GitLabStub(), _limited(1))) as client:
        response = await client.post("/mcp", content=body, headers=MCP_HEADERS)
    assert response.status_code == 401


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


async def test_a_notification_is_accepted_with_an_empty_202() -> None:
    headers = {**MCP_HEADERS, **AUTH, **VERSION}
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=INITIALIZED, headers=headers)
    assert response.status_code == 202
    assert response.content == b""


@pytest.mark.parametrize(
    ("json_response", "content_type"),
    [(False, "text/event-stream"), (True, "application/json")],
)
async def test_responses_are_sse_unless_json_is_configured(
    json_response: bool, content_type: str
) -> None:
    app = build_app(GitLabStub(), Settings(mcp_json_response=json_response))
    async with http_client(app) as client:
        response = await client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **AUTH})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert jsonrpc_message(response)["result"]["serverInfo"]["name"] == "mcp-gitlab"


async def test_an_unsupported_protocol_version_is_refused() -> None:
    headers = {**MCP_HEADERS, **AUTH, "MCP-Protocol-Version": "1999-01-01"}
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=PING, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] < 0


async def test_an_unsupported_protocol_version_is_named_with_the_supported_ones() -> None:
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2099-01-01",
        "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"_meta": meta}}
    headers = {
        **MCP_HEADERS,
        **AUTH,
        "MCP-Protocol-Version": "2099-01-01",
        "Mcp-Method": "tools/list",
    }
    async with http_client(build_app(GitLabStub())) as client:
        response = await client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "Unsupported protocol version"
    assert error["data"]["requested"] == "2099-01-01"
    assert "2026-07-28" in error["data"]["supported"]


async def open_session(client: httpx.AsyncClient) -> dict[str, Any]:
    """Initialize a stateful session and return the headers each later request in it carries."""
    opened = await client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **AUTH})
    assert opened.status_code == 200
    headers = {**MCP_HEADERS, **AUTH, **VERSION, "MCP-Session-Id": opened.headers["mcp-session-id"]}
    assert (await client.post("/mcp", json=INITIALIZED, headers=headers)).status_code == 202
    return headers


async def test_delete_ends_a_session_and_later_requests_get_404() -> None:
    async with http_client(build_app(GitLabStub(), Settings(mcp_stateless_http=False))) as client:
        session = await open_session(client)
        assert (await client.post("/mcp", json=PING, headers=session)).status_code == 200
        assert (await client.delete("/mcp", headers=session)).status_code == 200
        after = await client.post("/mcp", json=PING, headers=session)
    assert after.status_code == 404


async def test_an_idle_session_expires() -> None:
    settings = Settings(mcp_stateless_http=False, mcp_session_idle_timeout=1)
    async with http_client(build_app(GitLabStub(), settings)) as client:
        session = await open_session(client)
        await anyio.sleep(2.5)  # any request would restart the idle clock, so wait once
        response = await client.post("/mcp", json=PING, headers=session)
    assert response.status_code == 404


async def test_the_session_limit_refuses_one_more_session() -> None:
    settings = Settings(mcp_stateless_http=False, mcp_max_sessions=1)
    async with http_client(build_app(GitLabStub(), settings)) as client:
        await open_session(client)
        refused = await client.post("/mcp", json=INITIALIZE, headers={**MCP_HEADERS, **AUTH})
    assert refused.status_code == 503
