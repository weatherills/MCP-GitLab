import pytest

from mcp_gitlab.config import Settings
from mcp_gitlab.core.context import build_request_context, extract_credentials


def test_bearer_token_is_used() -> None:
    credentials = extract_credentials({"Authorization": "Bearer glpat-header"})
    assert credentials is not None and credentials.token == "glpat-header"


def test_bearer_scheme_is_case_insensitive() -> None:
    credentials = extract_credentials({"authorization": "bearer  glpat-x "})
    assert credentials is not None and credentials.token == "glpat-x"


def test_private_token_header_is_used() -> None:
    credentials = extract_credentials({"PRIVATE-TOKEN": "glpat-private"})
    assert credentials is not None and credentials.token == "glpat-private"


def test_authorization_takes_precedence_over_private_token() -> None:
    headers = {"Authorization": "Bearer glpat-a", "PRIVATE-TOKEN": "glpat-b"}
    credentials = extract_credentials(headers)
    assert credentials is not None and credentials.token == "glpat-a"


def test_non_bearer_authorization_is_ignored() -> None:
    assert extract_credentials({"Authorization": "Basic dXNlcjpwYXNz"}) is None


def test_no_credentials() -> None:
    assert extract_credentials({}) is None


def test_environment_token_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-server-side-abcdefgh")
    assert extract_credentials({}) is None
    assert build_request_context({}, Settings()).credentials is None


def test_token_is_hidden_from_repr() -> None:
    credentials = extract_credentials({"Authorization": "Bearer glpat-secret"})
    assert "glpat-secret" not in repr(credentials)


def test_toolsets_header_is_parsed() -> None:
    context = build_request_context({"X-MCP-Toolsets": "Projects, repository,"}, Settings())
    assert context.requested_toolsets == frozenset({"projects", "repository"})


def test_blank_toolsets_header_means_unspecified() -> None:
    assert build_request_context({"X-MCP-Toolsets": " , "}, Settings()).requested_toolsets is None


@pytest.mark.parametrize("value", ["true", "1", "YES", "on"])
def test_client_can_opt_into_read_only(value: str) -> None:
    assert build_request_context({"X-MCP-Readonly": value}, Settings()).read_only is True


def test_client_cannot_lift_operator_read_only() -> None:
    settings = Settings(gitlab_mcp_read_only=True)
    assert build_request_context({"X-MCP-Readonly": "false"}, settings).read_only is True


def test_safe_upstream_request_id_is_reused() -> None:
    context = build_request_context({"X-Request-ID": "abc-123.def_4"}, Settings())
    assert context.request_id == "abc-123.def_4"


def test_unsafe_upstream_request_id_is_replaced() -> None:
    context = build_request_context({"X-Request-ID": "bad\nid"}, Settings())
    assert context.request_id != "bad\nid"
    assert len(context.request_id) == 32
