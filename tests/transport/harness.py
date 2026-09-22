"""Run the real ASGI app in-process and talk to it with the MCP SDK's own client."""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from mcp_gitlab.app import create_app
from mcp_gitlab.config import Settings
from mcp_gitlab.tools import Toolset
from tests.fakes import ALL_FAKE_TOOLSETS, TOKEN
from tests.support import GitLabStub

BASE_URL = "http://127.0.0.1:8080"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def build_app(
    gitlab: GitLabStub | httpx.AsyncBaseTransport,
    settings: Settings | None = None,
    toolsets: Sequence[Toolset] = ALL_FAKE_TOOLSETS,
) -> Starlette:
    transport = gitlab.transport() if isinstance(gitlab, GitLabStub) else gitlab
    return create_app(settings or Settings(), toolsets=toolsets, gitlab_transport=transport)


@asynccontextmanager
async def running(app: Starlette) -> AsyncIterator[Starlette]:
    async with app.router.lifespan_context(app):
        yield app


@asynccontextmanager
async def http_client(app: Starlette, base_url: str = BASE_URL) -> AsyncIterator[httpx.AsyncClient]:
    async with running(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=base_url
        ) as client:
            yield client


@asynccontextmanager
async def client_session(
    app: Starlette, headers: Mapping[str, str] = AUTH
) -> AsyncIterator[ClientSession]:
    """An MCP client session against an app that is already running (see `running`)."""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport, base_url=BASE_URL, headers=dict(headers)
    ) as http:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=10) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def mcp_session(
    app: Starlette, headers: Mapping[str, str] = AUTH
) -> AsyncIterator[ClientSession]:
    async with running(app), client_session(app, headers) as session:
        yield session


def jsonrpc_message(response: httpx.Response) -> dict[str, Any]:
    """The JSON-RPC message in a Streamable HTTP response, whether JSON- or SSE-framed."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
        message: dict[str, Any] = json.loads(data[-1])
        return message
    body: dict[str, Any] = response.json()
    return body
