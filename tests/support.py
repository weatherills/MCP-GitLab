"""Shared test doubles."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class StubResponse:
    status: int = 200
    json: Any = None
    content: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)


StubItem = StubResponse | type[httpx.TransportError]


class GitLabStub:
    """Records outbound requests and replays canned responses keyed by (method, path).

    Paths are matched without the `/api/v4` prefix and without the query string.
    The last queued response for a route repeats once the queue is drained.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._routes: dict[tuple[str, str], list[StubItem]] = {}

    def add(self, method: str, path: str, *responses: StubItem) -> None:
        self._routes.setdefault((method.upper(), path), []).extend(responses)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def paths(self) -> list[str]:
        return [request.url.raw_path.decode() for request in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        raw_path = request.url.raw_path.decode().split("?", 1)[0]
        queue = self._routes.get((request.method, raw_path.removeprefix("/api/v4")))
        if not queue:
            return httpx.Response(
                404, json={"message": f"404 no stub for {request.method} {raw_path}"}
            )
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, type):
            raise item("stubbed transport failure", request=request)
        if item.content is not None:
            return httpx.Response(item.status, content=item.content, headers=item.headers)
        return httpx.Response(item.status, json=item.json, headers=item.headers)


class ChunkedStream(httpx.AsyncByteStream):
    """A response body with no Content-Length, delivered in chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
