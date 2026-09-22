"""End-to-end: the MCP SDK's own client against the real ASGI app, GitLab stubbed."""

import json
from typing import Any

import httpx
import pytest
from mcp.shared.exceptions import MCPError

from mcp_gitlab.config import Settings
from tests.fakes import TOKEN
from tests.support import GitLabStub, StubResponse
from tests.transport.harness import AUTH, BASE_URL, build_app, http_client, mcp_session

SCOPES = "/personal_access_tokens/self"


def tool_actions(tools: Any) -> dict[str, list[str]]:
    return {tool.name: tool.input_schema["properties"]["action"]["enum"] for tool in tools.tools}


async def test_negotiates_prd_target_protocol_and_identifies_itself() -> None:
    async with mcp_session(build_app(GitLabStub())) as session:
        assert session.protocol_version == "2025-11-25"


async def test_lists_tools_with_schema_and_annotations() -> None:
    async with mcp_session(build_app(GitLabStub())) as session:
        tools = await session.list_tools()
    [widgets] = tools.tools
    assert widgets.name == "fake_widgets"
    assert widgets.input_schema["properties"]["action"]["enum"] == [
        "list",
        "get",
        "create",
        "delete",
        "explode",
    ]
    assert "confirm" in widgets.input_schema["properties"]
    assert widgets.annotations is not None
    assert widgets.annotations.read_only_hint is False
    assert widgets.annotations.destructive_hint is True
    assert widgets.annotations.open_world_hint is True


async def test_call_returns_structured_and_text_content() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/grp%2Fapp/widgets", StubResponse(json=[{"name": "w1"}]))
    async with mcp_session(build_app(stub)) as session:
        result = await session.call_tool("fake_widgets", {"action": "list", "project": "grp/app"})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["items"] == [{"name": "w1"}]
    assert json.loads(result.content[0].text) == result.structured_content  # type: ignore[union-attr]
    assert stub.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"


async def test_destructive_call_without_confirm_is_a_tool_error() -> None:
    stub = GitLabStub()
    async with mcp_session(build_app(stub)) as session:
        result = await session.call_tool(
            "fake_widgets", {"action": "delete", "project": "1", "widget": "w"}
        )
    assert result.is_error is True
    assert result.structured_content == {
        "error": {
            "code": "confirmation_required",
            "message": "'delete' is destructive; call again with confirm=true to proceed.",
            "retryable": False,
        }
    }
    assert not [r for r in stub.requests if r.method == "DELETE"]


async def test_unknown_tool_is_a_protocol_error() -> None:
    async with mcp_session(build_app(GitLabStub())) as session:
        with pytest.raises(MCPError, match="Unknown tool"):
            await session.call_tool("no_such_tool", {"action": "list"})


async def test_read_only_header_hides_and_blocks_writes() -> None:
    async with mcp_session(build_app(GitLabStub()), {**AUTH, "X-MCP-Readonly": "true"}) as session:
        tools = await session.list_tools()
        result = await session.call_tool(
            "fake_widgets", {"action": "create", "project": "1", "widget": "w"}
        )
    assert tool_actions(tools) == {"fake_widgets": ["list", "get", "explode"]}
    assert tools.tools[0].annotations is not None
    assert tools.tools[0].annotations.read_only_hint is True
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "read_only_mode"


async def test_toolsets_header_selects_toolsets() -> None:
    async with mcp_session(
        build_app(GitLabStub()), {**AUTH, "X-MCP-Toolsets": "optional"}
    ) as session:
        tools = await session.list_tools()
        result = await session.call_tool("fake_gadgets", {"action": "list"})
    assert tool_actions(tools) == {"fake_gadgets": ["list"]}
    assert result.structured_content == {"items": ["g1", "g2"]}


async def test_token_scopes_shape_the_tool_list() -> None:
    stub = GitLabStub()
    stub.add("GET", SCOPES, StubResponse(json={"scopes": ["read_api"]}))
    async with mcp_session(build_app(stub)) as session:
        tools = await session.list_tools()
    assert tool_actions(tools) == {"fake_widgets": ["list", "get", "explode"]}


async def test_stateful_mode_is_supported() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/1/widgets/w", StubResponse(json={"name": "w"}))
    async with mcp_session(build_app(stub, Settings(mcp_stateless_http=False))) as session:
        result = await session.call_tool(
            "fake_widgets", {"action": "get", "project": "1", "widget": "w"}
        )
    assert result.structured_content == {"name": "w"}


async def test_server_with_no_toolsets_makes_no_gitlab_calls() -> None:
    stub = GitLabStub()
    async with mcp_session(build_app(stub, toolsets=())) as session:
        tools = await session.list_tools()
    assert tools.tools == []
    assert stub.requests == []


MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "e2e", "version": "0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


async def modern_call(
    client: httpx.AsyncClient, method: str, params: dict[str, Any], **headers: str
) -> dict[str, Any]:
    request_headers = {
        **AUTH,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
        **headers,
    }
    if method == "tools/call":
        request_headers["Mcp-Name"] = params["name"]
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {"_meta": MODERN_META, **params}}
    response = await client.post(f"{BASE_URL}/mcp", json=body, headers=request_headers)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload["result"]  # type: ignore[no-any-return]


async def test_2026_07_28_clients_are_served_statelessly() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/1/widgets/w", StubResponse(json={"name": "w"}))
    async with http_client(build_app(stub)) as client:
        listed = await modern_call(client, "tools/list", {}, **{"X-MCP-Readonly": "1"})
        called = await modern_call(
            client,
            "tools/call",
            {"name": "fake_widgets", "arguments": {"action": "get", "project": "1", "widget": "w"}},
        )
    assert listed["cacheScope"] == "private"
    assert listed["tools"][0]["inputSchema"]["properties"]["action"]["enum"] == [
        "list",
        "get",
        "explode",
    ]
    assert called["structuredContent"] == {"name": "w"}
