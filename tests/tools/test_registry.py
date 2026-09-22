import pytest

from mcp_gitlab.core.errors import (
    InvalidArgumentsError,
    ReadOnlyModeError,
    ToolsetDisabledError,
    UnknownActionError,
    UnknownToolError,
)
from mcp_gitlab.tools import Access, Action, NoParams, Tool, Toolset
from mcp_gitlab.tools.registry import ToolRegistry
from tests.fakes import ALL_FAKE_TOOLSETS, FAKE_TOOLSET, WIDGETS, list_gadgets, request_context


def visible_actions(
    registry: ToolRegistry, scopes: frozenset[str] | None = None, **ctx: object
) -> dict[str, list[str]]:
    views = registry.visible(request_context(**ctx), scopes)  # type: ignore[arg-type]
    return {view.tool.name: [a.name for a in view.actions] for view in views}


def test_duplicate_toolsets_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate toolset"):
        ToolRegistry([FAKE_TOOLSET, FAKE_TOOLSET])


def test_duplicate_tool_names_across_toolsets_are_rejected() -> None:
    clash = Toolset(name="clash", description="d", tools=(WIDGETS,))
    with pytest.raises(ValueError, match="Duplicate tool"):
        ToolRegistry([FAKE_TOOLSET, clash])


def test_unknown_server_allowlist_names_fail_fast() -> None:
    with pytest.raises(ValueError, match="unknown toolsets"):
        ToolRegistry(ALL_FAKE_TOOLSETS, server_allowlist=frozenset({"fake", "typo"}))


def test_defaults_enable_only_default_toolsets() -> None:
    registry = ToolRegistry(ALL_FAKE_TOOLSETS)
    assert registry.enabled_toolsets(request_context()) == frozenset({"fake"})


def test_server_allowlist_replaces_defaults() -> None:
    registry = ToolRegistry(ALL_FAKE_TOOLSETS, server_allowlist=frozenset({"optional"}))
    assert registry.enabled_toolsets(request_context()) == frozenset({"optional"})


def test_all_keyword_expands() -> None:
    registry = ToolRegistry(ALL_FAKE_TOOLSETS, server_allowlist=frozenset({"all"}))
    assert registry.enabled_toolsets(request_context()) == frozenset({"fake", "optional"})


def test_client_selects_within_the_server_ceiling() -> None:
    registry = ToolRegistry(ALL_FAKE_TOOLSETS, server_allowlist=frozenset({"fake"}))
    assert (
        registry.enabled_toolsets(request_context(toolsets=frozenset({"optional"}))) == frozenset()
    )
    assert registry.enabled_toolsets(request_context(toolsets=frozenset({"all"}))) == frozenset(
        {"fake"}
    )


def test_client_can_enable_non_default_toolsets_without_a_ceiling() -> None:
    registry = ToolRegistry(ALL_FAKE_TOOLSETS)
    selected = request_context(toolsets=frozenset({"optional", "nonexistent"}))
    assert registry.enabled_toolsets(selected) == frozenset({"optional"})


def test_read_only_hides_write_actions() -> None:
    actions = visible_actions(ToolRegistry(ALL_FAKE_TOOLSETS), read_only=True)
    assert actions == {"fake_widgets": ["list", "get", "explode"]}


def test_read_scoped_token_sees_only_reads() -> None:
    actions = visible_actions(ToolRegistry(ALL_FAKE_TOOLSETS), frozenset({"read_api"}))
    assert actions == {"fake_widgets": ["list", "get", "explode"]}


def test_api_scoped_token_sees_everything() -> None:
    actions = visible_actions(ToolRegistry(ALL_FAKE_TOOLSETS), frozenset({"api"}))
    assert actions["fake_widgets"] == ["list", "get", "create", "delete", "explode"]


def test_unrelated_scopes_hide_the_tool_entirely() -> None:
    assert visible_actions(ToolRegistry(ALL_FAKE_TOOLSETS), frozenset({"read_user"})) == {}


def test_action_specific_scopes_are_honoured() -> None:
    tool = Tool(
        name="files",
        description="d",
        actions=(
            Action(
                "read",
                "r",
                NoParams,
                list_gadgets,
                Access.READ,
                scopes=frozenset({"read_repository"}),
            ),
        ),
    )
    registry = ToolRegistry([Toolset(name="repo", description="d", tools=(tool,))])
    assert visible_actions(registry, frozenset({"read_repository"})) == {"files": ["read"]}


def test_resolve_unknown_tool() -> None:
    with pytest.raises(UnknownToolError):
        ToolRegistry(ALL_FAKE_TOOLSETS).resolve("nope", "list", request_context())


def test_resolve_tool_in_disabled_toolset() -> None:
    with pytest.raises(ToolsetDisabledError):
        ToolRegistry(ALL_FAKE_TOOLSETS).resolve("fake_gadgets", "list", request_context())


def test_resolve_requires_an_action() -> None:
    with pytest.raises(InvalidArgumentsError) as excinfo:
        ToolRegistry(ALL_FAKE_TOOLSETS).resolve("fake_widgets", None, request_context())
    assert "list" in excinfo.value.details["valid_actions"]


def test_resolve_unknown_action_lists_valid_ones() -> None:
    with pytest.raises(UnknownActionError) as excinfo:
        ToolRegistry(ALL_FAKE_TOOLSETS).resolve("fake_widgets", "frobnicate", request_context())
    assert excinfo.value.details["valid_actions"] == ["list", "get", "create", "delete", "explode"]


def test_resolve_enforces_read_only_even_for_direct_calls() -> None:
    with pytest.raises(ReadOnlyModeError):
        ToolRegistry(ALL_FAKE_TOOLSETS).resolve(
            "fake_widgets", "create", request_context(read_only=True)
        )
