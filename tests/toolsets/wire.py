"""Drive real toolset actions through the dispatcher and inspect what reaches GitLab."""

import importlib
import json
import pkgutil
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
    # Routes the action calls before this request, such as a read before a write:
    # (method, path, response).
    setup: tuple[tuple[str, str, StubResponse], ...] = ()

    @property
    def id(self) -> str:
        return f"{self.tool}.{self.arguments['action']}"

    def stub(self, stub: GitLabStub) -> None:
        """Queue this case's responses on the stub."""
        for method, path, response in self.setup:
            stub.add(method, path, response)
        stub.add(self.method, self.path, self.response)


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


def find_request(stub: GitLabStub, case: Case) -> httpx.Request:
    """The one request the case describes; an action may also make supporting calls."""
    matching = [
        request
        for request in stub.requests
        if request.method == case.method
        and request.url.raw_path.decode().split("?")[0] == f"/api/v4{case.path}"
    ]
    assert len(matching) == 1, (case.id, [f"{r.method} {r.url}" for r in stub.requests])
    return matching[0]


def assert_request(stub: GitLabStub, case: Case) -> None:
    request = find_request(stub, case)
    assert dict(request.url.params) == case.query, case.id
    assert body_of(request) == case.body, case.id


async def assert_wire(case: Case) -> ToolOutcome:
    stub = GitLabStub()
    case.stub(stub)
    outcome = await call(stub, case.tool, case.arguments)
    assert outcome.is_error is False, outcome.structured
    assert_request(stub, case)
    return outcome


def all_cases() -> list[Case]:
    """Every wire case, from each tests/toolsets/test_*.py module's CASES list."""
    import tests.toolsets as package

    cases: list[Case] = []
    for module in pkgutil.iter_modules(package.__path__):
        if module.name.startswith("test_"):
            imported = importlib.import_module(f"{package.__name__}.{module.name}")
            cases.extend(getattr(imported, "CASES", []))
    return cases
