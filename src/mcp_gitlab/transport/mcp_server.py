"""MCP protocol adapter: the only module that uses the SDK's server handler API.

Handlers rebuild the caller's context from each HTTP request's headers, so the
same code serves stateless and stateful Streamable HTTP, and both protocol eras
the SDK negotiates (2025-11-25 sessions and 2026-07-28 per-request envelopes).
"""

import json
from collections.abc import Mapping
from typing import Any

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError

from mcp_gitlab import __version__
from mcp_gitlab.config import Settings
from mcp_gitlab.core.context import RequestContext, build_request_context
from mcp_gitlab.core.errors import UnknownToolError
from mcp_gitlab.core.logging import bind_request_id
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.gitlab.scopes import resolve_token_scopes
from mcp_gitlab.tools.dispatcher import Dispatcher
from mcp_gitlab.tools.model import Access
from mcp_gitlab.tools.registry import ToolRegistry, ToolView
from mcp_gitlab.tools.schema import build_input_schema, describe_tool

SERVER_NAME = "mcp-gitlab"
INSTRUCTIONS = (
    "Tools for GitLab repositories. Each tool covers one area and takes an `action` argument. "
    "List actions are paginated with page/per_page; destructive actions require confirm=true."
)

RequestCtx = ServerRequestContext[Any, Any]


def build_mcp_server(
    *, settings: Settings, registry: ToolRegistry, dispatcher: Dispatcher, gitlab: GitLabClient
) -> Server[Any]:
    async def list_tools(
        ctx: RequestCtx, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        request = build_request_context(_headers(ctx), settings)
        with bind_request_id(request.request_id):
            scopes = await _token_scopes(request, registry, gitlab)
            tools = [_mcp_tool(view) for view in registry.visible(request, scopes)]
        # The list depends on the caller's token and headers, so it must never be shared.
        return types.ListToolsResult(tools=tools, cache_scope="private")

    async def call_tool(
        ctx: RequestCtx, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        request = build_request_context(_headers(ctx), settings)
        with bind_request_id(request.request_id):
            try:
                outcome = await dispatcher.call(params.name, params.arguments or {}, request)
            except UnknownToolError as exc:
                raise MCPError(code=types.INVALID_PARAMS, message=exc.message) from exc
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text", text=json.dumps(outcome.structured, ensure_ascii=False)
                )
            ],
            structured_content=outcome.structured,
            is_error=outcome.is_error,
        )

    return Server(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def _headers(ctx: RequestCtx) -> Mapping[str, str]:
    headers = getattr(ctx.request, "headers", None)
    return headers if isinstance(headers, Mapping) else {}


async def _token_scopes(
    request: RequestContext, registry: ToolRegistry, gitlab: GitLabClient
) -> frozenset[str] | None:
    if request.credentials is None or not registry.enabled_toolsets(request):
        return None
    return await resolve_token_scopes(gitlab.session(request.credentials.token))


def _mcp_tool(view: ToolView) -> types.Tool:
    reads_only = all(action.access is Access.READ for action in view.actions)
    return types.Tool(
        name=view.tool.name,
        title=view.tool.title,
        description=describe_tool(view.tool, view.actions),
        input_schema=build_input_schema(view.tool, view.actions),
        annotations=types.ToolAnnotations(
            title=view.tool.title,
            read_only_hint=reads_only,
            destructive_hint=None
            if reads_only
            else any(action.destructive for action in view.actions),
            open_world_hint=True,
        ),
    )
