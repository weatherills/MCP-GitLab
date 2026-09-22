import pytest
from pydantic import ValidationError

from mcp_gitlab.tools import Access, Action, ActionParams, NoParams, PageParams, Tool, Toolset
from tests.fakes import list_gadgets


def action(name: str = "list", **overrides: object) -> Action:
    fields: dict[str, object] = {
        "name": name,
        "description": "d",
        "params": NoParams,
        "handler": list_gadgets,
        "access": Access.READ,
    }
    fields.update(overrides)
    return Action(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["List", "list-items", "1list", ""])
def test_action_names_must_be_snake_case(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid action name"):
        action(name)


def test_reserved_parameter_names_are_rejected() -> None:
    class Bad(ActionParams):
        confirm: bool = False

    with pytest.raises(ValueError, match="reserved"):
        action(params=Bad)


def test_params_must_forbid_extras() -> None:
    from pydantic import BaseModel

    class Loose(BaseModel):
        x: int = 0

    with pytest.raises(TypeError, match="ActionParams"):
        action(params=Loose)


def test_only_write_actions_can_be_destructive() -> None:
    with pytest.raises(ValueError, match="only write actions"):
        action(destructive=True)


def test_tool_rejects_duplicate_actions() -> None:
    with pytest.raises(ValueError, match="duplicated"):
        Tool(name="t", description="d", actions=(action("list"), action("list")))


def test_tool_needs_actions() -> None:
    with pytest.raises(ValueError, match="no actions"):
        Tool(name="t", description="d", actions=())


def test_toolset_name_all_is_reserved() -> None:
    tool = Tool(name="t", description="d", actions=(action(),))
    with pytest.raises(ValueError, match="reserved"):
        Toolset(name="all", description="d", tools=(tool,))


def test_page_params_defaults_and_bounds() -> None:
    assert PageParams().page_query() == {"page": 1, "per_page": 20}
    with pytest.raises(ValidationError):
        PageParams(per_page=101)
    with pytest.raises(ValidationError):
        PageParams(page=0)


def test_action_params_reject_unknown_arguments() -> None:
    with pytest.raises(ValidationError):
        NoParams.model_validate({"surprise": 1})
