"""Every action any toolset registers must have at least one wire case."""

from mcp_gitlab.toolsets import TOOLSETS
from tests.toolsets.wire import all_cases


def test_every_registered_action_has_a_wire_case() -> None:
    registered = {
        f"{tool.name}.{action.name}"
        for toolset in TOOLSETS
        for tool in toolset.tools
        for action in tool.actions
    }
    covered = {case.id for case in all_cases()}
    assert registered - covered == set(), "actions without a wire case"
    assert covered - registered == set(), "wire cases for actions that don't exist"
