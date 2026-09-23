"""Every tool the model is given, used the way the model uses it: listed, then called over MCP.

For each tool, each wire case's arguments are validated against the input schema that
tools/list advertises, sent through the real MCP client and Streamable HTTP transport, and
the GitLab request they produce is checked against the case.
"""

from collections import defaultdict

import jsonschema
import pytest

from mcp_gitlab.config import Settings
from mcp_gitlab.toolsets import TOOLSETS
from tests.support import GitLabStub
from tests.toolsets.wire import Case, all_cases, assert_request
from tests.transport.harness import build_app, client_session, running

TOOL_NAMES = sorted(tool.name for toolset in TOOLSETS for tool in toolset.tools)


def cases_by_tool() -> dict[str, list[Case]]:
    grouped: dict[str, list[Case]] = defaultdict(list)
    for case in all_cases():
        grouped[case.tool].append(case)
    return grouped


CASES = cases_by_tool()


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
async def test_tool_works_over_mcp(tool_name: str) -> None:
    stub = GitLabStub()
    app = build_app(stub, Settings(gitlab_mcp_toolsets="all"), toolsets=TOOLSETS)
    async with running(app), client_session(app) as session:
        listed = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert tool_name in listed, f"{tool_name} is not offered by tools/list"
        schema = listed[tool_name].input_schema
        jsonschema.Draft202012Validator.check_schema(schema)
        assert CASES[tool_name], f"{tool_name} has no wire cases"
        for case in CASES[tool_name]:
            jsonschema.validate(case.arguments, schema)
            stub.reset()
            case.stub(stub)
            result = await session.call_tool(tool_name, case.arguments)
            assert result.is_error is False, (case.id, result.structured_content)
            assert_request(stub, case)
