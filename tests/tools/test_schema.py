import pytest
from pydantic import Field

from mcp_gitlab.tools import Access, Action, ActionParams, Tool
from mcp_gitlab.tools.schema import SchemaConflictError, build_input_schema, describe_tool
from tests.fakes import WIDGETS, list_gadgets


def test_flat_schema_lists_actions_and_all_parameters() -> None:
    schema = build_input_schema(WIDGETS, WIDGETS.actions)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == ["list", "get", "create", "delete", "explode"]
    assert {"project", "search", "page", "per_page", "widget", "colour", "confirm"} <= schema[
        "properties"
    ].keys()


def test_parameters_required_by_every_visible_action_are_required() -> None:
    subset = [WIDGETS.action("get"), WIDGETS.action("delete")]
    schema = build_input_schema(WIDGETS, [a for a in subset if a])
    assert schema["required"] == ["action", "project", "widget"]


def test_partial_parameters_are_annotated_not_required() -> None:
    schema = build_input_schema(WIDGETS, WIDGETS.actions)
    assert schema["required"] == ["action"]
    properties = schema["properties"]
    assert properties["widget"]["description"].endswith("(required for: get, create, delete)")
    assert properties["colour"]["description"].endswith("(used by: create)")
    assert "used by" not in properties["project"]["description"]


def test_confirm_appears_only_when_a_destructive_action_is_visible() -> None:
    reads = [a for a in WIDGETS.actions if a.access is Access.READ]
    assert "confirm" not in build_input_schema(WIDGETS, reads)["properties"]
    confirm = build_input_schema(WIDGETS, WIDGETS.actions)["properties"]["confirm"]
    assert confirm["type"] == "boolean"
    assert "delete" in confirm["description"]


def test_generated_titles_are_stripped_but_a_title_parameter_survives() -> None:
    class Params(ActionParams):
        title: str = Field(description="Merge request title.")

    tool = Tool(
        name="t",
        description="d",
        actions=(Action("create", "c", Params, list_gadgets, Access.WRITE),),
    )
    schema = build_input_schema(tool, tool.actions)
    assert "title" in schema["properties"]
    assert "title" not in schema["properties"]["title"]


def test_conflicting_parameter_shapes_are_rejected() -> None:
    class A(ActionParams):
        limit: int = 1

    class B(ActionParams):
        limit: str = "1"

    tool = Tool(
        name="t",
        description="d",
        actions=(
            Action("a", "a", A, list_gadgets, Access.READ),
            Action("b", "b", B, list_gadgets, Access.READ),
        ),
    )
    with pytest.raises(SchemaConflictError, match="'limit'"):
        build_input_schema(tool, tool.actions)


def test_nested_models_of_one_name_must_agree_across_actions() -> None:
    # Each action's JSON schema names nested models by class name, and the tool shares one $defs.
    def entry_model(value_type: type) -> type[ActionParams]:
        class Entry(ActionParams):
            key: str
            value: value_type  # type: ignore[valid-type]

        return Entry

    first, second = entry_model(str), entry_model(int)

    class A(ActionParams):
        entries: list[first] | None = None  # type: ignore[valid-type]

    class B(ActionParams):
        others: list[second] | None = None  # type: ignore[valid-type]

    tool = Tool(
        name="t",
        description="d",
        actions=(
            Action("a", "a", A, list_gadgets, Access.READ),
            Action("b", "b", B, list_gadgets, Access.READ),
        ),
    )
    with pytest.raises(SchemaConflictError, match="nested model 'Entry'"):
        build_input_schema(tool, tool.actions)


def test_a_parameter_optional_for_one_action_and_required_for_another_is_one_parameter() -> None:
    class Create(ActionParams):
        title: str = Field(min_length=1, description="Title.")

    class Update(ActionParams):
        title: str | None = Field(default=None, min_length=1, description="New title.")

    tool = Tool(
        name="t",
        description="d",
        actions=(
            Action("update", "u", Update, list_gadgets, Access.WRITE),
            Action("create", "c", Create, list_gadgets, Access.WRITE),
        ),
    )
    title = build_input_schema(tool, tool.actions)["properties"]["title"]
    assert title["type"] == "string" and title["minLength"] == 1
    assert "anyOf" not in title and "default" not in title
    assert title["description"] == "Title. (required for: create)"


def test_a_shared_annotated_type_matches_its_optional_use() -> None:
    from typing import Annotated

    Thread = Annotated[str, Field(min_length=1, description="Thread ID.")]

    class Reply(ActionParams):
        thread: Thread

    class Edit(ActionParams):
        thread: Thread | None = Field(default=None, description="Thread, for a reply.")

    tool = Tool(
        name="t",
        description="d",
        actions=(
            Action("edit", "e", Edit, list_gadgets, Access.WRITE),
            Action("reply", "r", Reply, list_gadgets, Access.WRITE),
        ),
    )
    thread = build_input_schema(tool, tool.actions)["properties"]["thread"]
    assert thread["type"] == "string"
    assert thread["description"].startswith("Thread ID.")


def test_optional_parameters_must_still_agree_on_their_type() -> None:
    class A(ActionParams):
        limit: int | None = None

    class B(ActionParams):
        limit: str

    tool = Tool(
        name="t",
        description="d",
        actions=(
            Action("a", "a", A, list_gadgets, Access.READ),
            Action("b", "b", B, list_gadgets, Access.READ),
        ),
    )
    with pytest.raises(SchemaConflictError, match="'limit'"):
        build_input_schema(tool, tool.actions)


def test_description_flags_writes_and_destructive_actions() -> None:
    text = describe_tool(WIDGETS, WIDGETS.actions)
    assert text.startswith("Manage widgets in a project.")
    assert "- list: List widgets." in text
    assert "- create: Create a widget. [writes to GitLab]" in text
    assert "destructive: requires confirm=true" in text
