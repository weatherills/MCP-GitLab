"""Outbound GitLab REST adapter (PRD-00 sections 7 and 10).

`GitLabClient` is created once per process and holds only immutable settings and
a connection pool. Every call takes the caller's token explicitly; a
`GitLabSession` merely binds that token for the duration of one tool call.
"""

import http.cookiejar
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx

from mcp_gitlab import __version__
from mcp_gitlab.config import Settings
from mcp_gitlab.core.errors import (
    GitLabError,
    GitLabUnavailableError,
    PayloadTooLargeError,
    gitlab_error_type,
)
from mcp_gitlab.core.logging import log_event
from mcp_gitlab.gitlab.pagination import Page, PageInfo
from mcp_gitlab.gitlab.retry import RetryPolicy, retry_after_seconds

logger = logging.getLogger(__name__)

Params = Mapping[str, Any]
Sleep = Callable[[float], Awaitable[None]]

_MESSAGE_KEYS = ("message", "error_description", "error")
_MAX_ERROR_TEXT = 2000


@dataclass(frozen=True, slots=True)
class GitLabResponse:
    status: int
    headers: httpx.Headers
    content: bytes

    def json(self) -> Any:
        if not self.content:
            return None
        try:
            return json.loads(self.content)
        except ValueError as exc:
            raise GitLabError(
                "GitLab returned a response that is not valid JSON.", status=self.status
            ) from exc

    @property
    def page_info(self) -> PageInfo:
        return PageInfo.from_headers(self.headers)


class GitLabClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retry: RetryPolicy | None = None,
        sleep: Sleep = anyio.sleep,
    ) -> None:
        self._base_url = str(settings.gitlab_base_url).rstrip("/")
        self._max_response_bytes = settings.gitlab_max_response_bytes
        self._retry = retry or RetryPolicy(max_retries=settings.gitlab_max_retries)
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            timeout=settings.gitlab_timeout_seconds,
            verify=_tls_verification(settings),
            transport=transport,
            follow_redirects=False,
            cookies=_DiscardingCookieJar(),
            headers={"User-Agent": f"mcp-gitlab/{__version__}", "Accept": "application/json"},
        )

    def session(self, token: str) -> "GitLabSession":
        return GitLabSession(self, token)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        params: Params | None = None,
        json_body: Any = None,
        max_bytes: int | None = None,
    ) -> GitLabResponse:
        method = method.upper()
        path = path if path.startswith("/") else f"/{path}"
        limit = max_bytes or self._max_response_bytes
        status_retries = network_retries = 0
        while True:
            attempt = status_retries + network_retries + 1
            started = time.perf_counter()
            try:
                response = await self._send(method, path, token, params, json_body, limit)
            except httpx.TransportError as exc:
                self._log(method, path, started, attempt, status=None, error=type(exc).__name__)
                delay = self._retry.delay_after_transport_error(method, exc, network_retries)
                if delay is None:
                    raise GitLabUnavailableError(
                        f"Could not reach GitLab for {method} {path} ({type(exc).__name__})."
                    ) from exc
                network_retries += 1
                await self._sleep(delay)
                continue

            self._log(
                method,
                path,
                started,
                attempt,
                status=response.status,
                gitlab_request_id=response.headers.get("x-request-id"),
            )
            if response.status < 400:
                return response
            delay = self._retry.delay_after_status(
                method, response.status, response.headers, status_retries
            )
            if delay is None:
                raise _error_from_response(method, path, response)
            status_retries += 1
            await self._sleep(delay)

    async def _send(
        self,
        method: str,
        path: str,
        token: str,
        params: Params | None,
        json_body: Any,
        max_bytes: int,
    ) -> GitLabResponse:
        request = self._http.build_request(
            method,
            self._base_url + path,
            params=_without_none(params),
            json=json_body,
            headers={"Authorization": f"Bearer {token}"},
        )
        response = await self._http.send(request, stream=True)
        try:
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise _too_large(method, path, max_bytes)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise _too_large(method, path, max_bytes)
            return GitLabResponse(response.status_code, response.headers, bytes(body))
        finally:
            await response.aclose()

    def _log(self, method: str, path: str, started: float, attempt: int, **fields: Any) -> None:
        log_event(
            logger,
            logging.INFO,
            "gitlab_request",
            method=method,
            path=path,
            attempt=attempt,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            **fields,
        )


@dataclass(frozen=True, slots=True)
class GitLabSession:
    """A `GitLabClient` bound to one caller's token for the duration of one tool call."""

    client: GitLabClient
    token: str = field(repr=False)

    async def get(
        self, path: str, *, params: Params | None = None, max_bytes: int | None = None
    ) -> Any:
        return (await self._request("GET", path, params=params, max_bytes=max_bytes)).json()

    async def get_page(self, path: str, *, params: Params | None = None) -> Page:
        response = await self._request("GET", path, params=params)
        items = response.json()
        if not isinstance(items, list):
            raise GitLabError(f"Expected a list from GET {path}.", status=response.status)
        return Page(items=items, info=response.page_info)

    async def get_bytes(
        self, path: str, *, params: Params | None = None, max_bytes: int | None = None
    ) -> bytes:
        return (await self._request("GET", path, params=params, max_bytes=max_bytes)).content

    async def post(self, path: str, *, json_body: Any = None, params: Params | None = None) -> Any:
        return (await self._request("POST", path, params=params, json_body=json_body)).json()

    async def put(self, path: str, *, json_body: Any = None, params: Params | None = None) -> Any:
        return (await self._request("PUT", path, params=params, json_body=json_body)).json()

    async def delete(self, path: str, *, params: Params | None = None) -> Any:
        return (await self._request("DELETE", path, params=params)).json()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        json_body: Any = None,
        max_bytes: int | None = None,
    ) -> GitLabResponse:
        return await self.client.request(
            method, path, token=self.token, params=params, json_body=json_body, max_bytes=max_bytes
        )


class _DiscardingCookieJar(http.cookiejar.CookieJar):
    """The connection pool is shared by every caller, so no response may leave state behind."""

    def set_cookie(self, cookie: http.cookiejar.Cookie) -> None:
        return None


def _tls_verification(settings: Settings) -> ssl.SSLContext | bool:
    """System CAs by default, an explicit bundle for self-hosted CAs (PRD-00 section 7.4)."""
    if settings.gitlab_skip_tls_verify:
        return False
    return ssl.create_default_context(cafile=settings.gitlab_ca_bundle)


def _without_none(params: Params | None) -> dict[str, Any] | None:
    if params is None:
        return None
    return {key: value for key, value in params.items() if value is not None}


def _too_large(method: str, path: str, max_bytes: int) -> PayloadTooLargeError:
    return PayloadTooLargeError(
        f"GitLab's response to {method} {path} exceeds the {max_bytes}-byte limit.",
        details={"max_bytes": max_bytes},
    )


def _error_from_response(method: str, path: str, response: GitLabResponse) -> GitLabError:
    message = _gitlab_message(response.content)
    summary = (
        message if isinstance(message, str) else json.dumps(message) if message is not None else ""
    )
    text = f"GitLab returned {response.status} for {method} {path}" + (
        f": {summary}" if summary else "."
    )
    details: dict[str, Any] = {}
    if message is not None:
        details["gitlab_message"] = message
    if response.status == 429:
        retry_after = retry_after_seconds(response.headers)
        if retry_after is not None:
            details["retry_after_seconds"] = retry_after
    return gitlab_error_type(response.status)(text, status=response.status, details=details)


def _gitlab_message(content: bytes) -> Any:
    """GitLab's own error message, passed through to the caller (PRD-00 section 10)."""
    if not content:
        return None
    try:
        body = json.loads(content)
    except ValueError:
        return content.decode("utf-8", "replace")[:_MAX_ERROR_TEXT]
    if isinstance(body, dict):
        for key in _MESSAGE_KEYS:
            if key in body:
                return _bounded(body[key])
    return _bounded(body)


def _bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_MAX_ERROR_TEXT]
    if len(json.dumps(value, default=str)) > _MAX_ERROR_TEXT:
        return json.dumps(value, default=str)[:_MAX_ERROR_TEXT]
    return value
