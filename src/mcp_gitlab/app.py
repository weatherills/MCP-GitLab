"""Composition root: the one place that wires settings, adapters and toolsets together."""

from collections.abc import Sequence

import httpx
from starlette.applications import Starlette

from mcp_gitlab.config import Settings
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.tools.dispatcher import Dispatcher
from mcp_gitlab.tools.model import Toolset
from mcp_gitlab.tools.registry import ToolRegistry
from mcp_gitlab.toolsets import TOOLSETS
from mcp_gitlab.transport.http import build_http_app
from mcp_gitlab.transport.mcp_server import build_mcp_server


def create_app(
    settings: Settings | None = None,
    *,
    toolsets: Sequence[Toolset] = TOOLSETS,
    gitlab_transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    """Build the ASGI app. Also usable as `uvicorn mcp_gitlab.app:create_app --factory`."""
    settings = settings or Settings()
    registry = ToolRegistry(toolsets, server_allowlist=settings.toolset_allowlist())
    gitlab = GitLabClient(settings, transport=gitlab_transport)
    dispatcher = Dispatcher(registry, gitlab, settings)
    mcp_server = build_mcp_server(
        settings=settings, registry=registry, dispatcher=dispatcher, gitlab=gitlab
    )
    return build_http_app(settings=settings, mcp_server=mcp_server, gitlab=gitlab)
