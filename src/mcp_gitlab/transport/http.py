"""HTTP composition: /mcp behind the credential gate and DNS-rebinding protection, plus /healthz."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_gitlab import __version__
from mcp_gitlab.config import Settings
from mcp_gitlab.core.context import MISSING_TOKEN_MESSAGE, extract_credentials
from mcp_gitlab.gitlab.client import GitLabClient

MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"


class RequireCredentials:
    """Every /mcp request must carry its caller's PAT; there is no server-side fallback."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and extract_credentials(Headers(scope=scope)) is None:
            response = JSONResponse(
                {
                    "error": {
                        "code": "authentication_required",
                        "message": MISSING_TOKEN_MESSAGE,
                        "retryable": False,
                    }
                },
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="mcp-gitlab"'},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


class RefuseStandaloneStream:
    """Stateless mode has no session to push to, so the standalone GET stream is refused (405)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "GET":
            response = JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Method Not Allowed: this server is stateless and has no "
                        "standalone SSE stream; responses arrive on each POST.",
                    },
                },
                status_code=405,
                headers={"Allow": "POST"},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


def build_http_app(
    *, settings: Settings, mcp_server: Server[Any], gitlab: GitLabClient
) -> Starlette:
    session_manager = StreamableHTTPSessionManager(app=mcp_server, **_session_options(settings))

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                yield
            finally:
                await gitlab.aclose()

    mcp_app: ASGIApp = StreamableHTTPASGIApp(session_manager)
    if settings.mcp_stateless_http:
        mcp_app = RefuseStandaloneStream(mcp_app)

    return Starlette(
        routes=[
            Route(MCP_PATH, endpoint=RequireCredentials(mcp_app)),
            Route(HEALTH_PATH, endpoint=healthz, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def _session_options(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "stateless": settings.mcp_stateless_http,
        # SSE by default; one plain JSON body per request when the deployment asks (PRD-00 §4.2).
        "json_response": settings.mcp_json_response,
        # The SDK only enables DNS-rebinding protection by itself on loopback binds.
        "security_settings": TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts(),
            allowed_origins=settings.allowed_origins(),
        ),
    }
    if not settings.mcp_stateless_http:
        options["session_idle_timeout"] = settings.mcp_session_idle_timeout
        if settings.mcp_max_sessions is not None:
            options["max_sessions"] = settings.mcp_max_sessions
    return options
