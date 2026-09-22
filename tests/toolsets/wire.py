"""Drive real toolset actions through the dispatcher and inspect what reaches GitLab."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from mcp_gitlab.config import Settings
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.tools.dispatcher import Dispatcher, ToolOutcome
from mcp_gitlab.tools.registry import ToolRegistry
from mcp_gitlab.toolsets import TOOLSETS
from tests.fakes import request_context
from tests.support import GitLabStub, RecordingSleep, StubResponse


@dataclass
class Case:
    tool: str
    arguments: dict[str, Any]
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    response: StubResponse = field(default_factory=lambda: StubResponse(json={}))

    @property
    def id(self) -> str:
        return f"{self.tool}.{self.arguments['action']}"


def dispatcher(stub: GitLabStub, settings: Settings | None = None) -> Dispatcher:
    settings = settings or Settings()
    client = GitLabClient(settings, transport=stub.transport(), sleep=RecordingSleep())
    return Dispatcher(ToolRegistry(TOOLSETS), client, settings)


async def call(
    stub: GitLabStub, tool: str, arguments: dict[str, Any], settings: Settings | None = None
) -> ToolOutcome:
    return await dispatcher(stub, settings).call(tool, arguments, request_context())


def body_of(request: httpx.Request) -> Any:
    return json.loads(request.content) if request.content else None


async def assert_wire(case: Case) -> ToolOutcome:
    stub = GitLabStub()
    stub.add(case.method, case.path, case.response)
    outcome = await call(stub, case.tool, case.arguments)
    assert outcome.is_error is False, outcome.structured
    request = stub.requests[-1]
    assert request.method == case.method
    assert request.url.raw_path.decode().split("?")[0] == f"/api/v4{case.path}"
    assert dict(request.url.params) == case.query
    assert body_of(request) == case.body
    return outcome
