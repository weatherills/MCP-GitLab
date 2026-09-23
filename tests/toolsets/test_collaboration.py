"""PRD-08 toolset `collaboration`: gitlab_members, gitlab_users, gitlab_wikis, gitlab_webhooks,
gitlab_snippets."""

import logging
from typing import Any

import pytest

from mcp_gitlab.tools.registry import ToolRegistry
from mcp_gitlab.toolsets import TOOLSETS
from tests.fakes import request_context
from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
PAGE = {"page": "1", "per_page": "20"}
MEMBER = {"id": 7, "username": "ada", "access_level": 30}
HOOK_URL = "https://ci.example.com/hook"
SECRET = "s3cret-hook-token"
SNIPPET = f"{P}/snippets/21"

CASES = [
    Case(
        "gitlab_members",
        {"action": "list", "project": "grp/app", "query": "ada"},
        "GET",
        f"{P}/members",
        {**PAGE, "query": "ada"},
        response=LIST,
    ),
    Case(
        "gitlab_members",
        {"action": "list", "project": "grp/app", "inherited": True},
        "GET",
        f"{P}/members/all",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_members",
        {"action": "get", "project": "grp/app", "user_id": 7},
        "GET",
        f"{P}/members/7",
        response=StubResponse(json=MEMBER),
    ),
    Case(
        "gitlab_members",
        {"action": "get", "project": "grp/app", "user_id": 7, "inherited": True},
        "GET",
        f"{P}/members/all/7",
        response=StubResponse(json=MEMBER),
    ),
    Case(
        "gitlab_members",
        {
            "action": "add",
            "project": "grp/app",
            "username": "ada",
            "access_level": "developer",
            "expires_at": "2026-12-31",
        },
        "POST",
        f"{P}/members",
        body={"username": "ada", "access_level": 30, "expires_at": "2026-12-31"},
        response=StubResponse(status=201, json=MEMBER),
    ),
    Case(
        "gitlab_members",
        {
            "action": "update",
            "project": "grp/app",
            "user_id": 7,
            "access_level": 40,
            "confirm": True,
        },
        "PUT",
        f"{P}/members/7",
        body={"access_level": 40},
        response=StubResponse(json={**MEMBER, "access_level": 40}),
    ),
    Case(
        "gitlab_members",
        {
            "action": "remove",
            "project": "grp/app",
            "user_id": 7,
            "unassign_issuables": True,
            "confirm": True,
        },
        "DELETE",
        f"{P}/members/7",
        {"unassign_issuables": "true"},
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_members",
        {"action": "list_group_members", "group": "grp/sub", "inherited": True},
        "GET",
        "/groups/grp%2Fsub/members/all",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_users",
        {"action": "get_current"},
        "GET",
        "/user",
        response=StubResponse(json={"id": 1, "username": "me"}),
    ),
    Case("gitlab_users", {"action": "get", "user_id": 7}, "GET", "/users/7"),
    Case(
        "gitlab_users",
        {"action": "search", "search": "ada"},
        "GET",
        "/users",
        {**PAGE, "search": "ada"},
        response=LIST,
    ),
    Case(
        "gitlab_wikis",
        {"action": "list", "project": "grp/app"},
        "GET",
        f"{P}/wikis",
        {"with_content": "false"},
        response=LIST,
    ),
    Case(
        "gitlab_wikis",
        {"action": "get", "project": "grp/app", "slug": "docs/setup", "version": "abc123"},
        "GET",
        f"{P}/wikis/docs%2Fsetup",
        {"version": "abc123"},
    ),
    Case(
        "gitlab_wikis",
        {"action": "create", "project": "grp/app", "title": "docs/Setup", "content": "# Setup"},
        "POST",
        f"{P}/wikis",
        body={"title": "docs/Setup", "content": "# Setup"},
        response=StubResponse(status=201, json={"slug": "docs/Setup", "format": "markdown"}),
    ),
    Case(
        "gitlab_wikis",
        {
            "action": "update",
            "project": "grp/app",
            "slug": "docs/setup",
            "content": "# Setup, v2",
            "format": "markdown",
        },
        "PUT",
        f"{P}/wikis/docs%2Fsetup",
        body={"content": "# Setup, v2", "format": "markdown"},
        response=StubResponse(json={"slug": "docs/setup", "format": "markdown"}),
    ),
    Case(
        "gitlab_wikis",
        {"action": "delete", "project": "grp/app", "slug": "docs/setup"},
        "DELETE",
        f"{P}/wikis/docs%2Fsetup",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {"action": "list", "project": "grp/app"},
        "GET",
        f"{P}/hooks",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_webhooks",
        {"action": "get", "project": "grp/app", "hook_id": 3},
        "GET",
        f"{P}/hooks/3",
    ),
    Case(
        "gitlab_webhooks",
        {
            "action": "create",
            "project": "grp/app",
            "url": HOOK_URL,
            "name": "CI",
            "token": SECRET,
            "push_events": False,
            "merge_requests_events": True,
        },
        "POST",
        f"{P}/hooks",
        body={
            "url": HOOK_URL,
            "name": "CI",
            "token": SECRET,
            "push_events": False,
            "merge_requests_events": True,
        },
        response=StubResponse(status=201, json={"id": 3, "url": HOOK_URL}),
    ),
    Case(
        "gitlab_webhooks",
        {"action": "update", "project": "grp/app", "hook_id": 3, "pipeline_events": True},
        "PUT",
        f"{P}/hooks/3",
        body={"pipeline_events": True},
    ),
    Case(
        "gitlab_webhooks",
        {"action": "delete", "project": "grp/app", "hook_id": 3},
        "DELETE",
        f"{P}/hooks/3",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {"action": "test", "project": "grp/app", "hook_id": 3, "trigger": "push_events"},
        "POST",
        f"{P}/hooks/3/test/push_events",
        response=StubResponse(status=201, json={"message": "201 Created"}),
    ),
    Case(
        "gitlab_webhooks",
        {
            "action": "set_custom_header",
            "project": "grp/app",
            "hook_id": 3,
            "key": "Authorization",
            "value": SECRET,
        },
        "PUT",
        f"{P}/hooks/3/custom_headers/Authorization",
        body={"value": SECRET},
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {"action": "delete_custom_header", "project": "grp/app", "hook_id": 3, "key": "X-Env"},
        "DELETE",
        f"{P}/hooks/3/custom_headers/X-Env",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {
            "action": "set_url_variable",
            "project": "grp/app",
            "hook_id": 3,
            "key": "tenant",
            "value": SECRET,
        },
        "PUT",
        f"{P}/hooks/3/url_variables/tenant",
        body={"value": SECRET},
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {"action": "delete_url_variable", "project": "grp/app", "hook_id": 3, "key": "tenant"},
        "DELETE",
        f"{P}/hooks/3/url_variables/tenant",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_webhooks",
        {
            "action": "create",
            "project": "grp/app",
            "url": "https://ci.example.com/hook/{tenant}",
            "custom_headers": [{"key": "Authorization", "value": SECRET}],
            "url_variables": [{"key": "tenant", "value": "acme"}],
        },
        "POST",
        f"{P}/hooks",
        body={
            "url": "https://ci.example.com/hook/{tenant}",
            "custom_headers": [{"key": "Authorization", "value": SECRET}],
            "url_variables": [{"key": "tenant", "value": "acme"}],
        },
        response=StubResponse(status=201, json={"id": 3}),
    ),
    Case(
        "gitlab_members",
        {
            "action": "update",
            "project": "grp/app",
            "user_id": 7,
            "access_level": "developer",
            "clear_expiry": True,
            "confirm": True,
        },
        "PUT",
        f"{P}/members/7",
        body={"access_level": 30, "expires_at": None},
        response=StubResponse(json=MEMBER),
    ),
    Case(
        "gitlab_snippets",
        {"action": "list", "project": "grp/app"},
        "GET",
        f"{P}/snippets",
        PAGE,
        response=LIST,
    ),
    Case("gitlab_snippets", {"action": "list"}, "GET", "/snippets", PAGE, response=LIST),
    Case(
        "gitlab_snippets",
        {"action": "list", "scope": "public"},
        "GET",
        "/snippets/public",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_snippets",
        {"action": "list", "scope": "all"},
        "GET",
        "/snippets/all",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_snippets", {"action": "get", "project": "grp/app", "snippet_id": 21}, "GET", SNIPPET
    ),
    Case("gitlab_snippets", {"action": "get", "snippet_id": 5}, "GET", "/snippets/5"),
    Case(
        "gitlab_snippets",
        {"action": "get_content", "project": "grp/app", "snippet_id": 21},
        "GET",
        f"{SNIPPET}/raw",
        response=StubResponse(content=b"print('hi')\n"),
    ),
    Case(
        "gitlab_snippets",
        {"action": "get_content", "snippet_id": 5, "file_path": "lib/util.py"},
        "GET",
        "/snippets/5/files/HEAD/lib%2Futil.py/raw",
        response=StubResponse(content=b"x = 1\n"),
    ),
    Case(
        "gitlab_snippets",
        {
            "action": "create",
            "project": "grp/app",
            "title": "Retry helper",
            "file_name": "retry.py",
            "content": "def retry(): ...",
        },
        "POST",
        f"{P}/snippets",
        body={
            "visibility": "private",
            "title": "Retry helper",
            "file_name": "retry.py",
            "content": "def retry(): ...",
        },
        response=StubResponse(status=201, json={"id": 21}),
    ),
    Case(
        "gitlab_snippets",
        {
            "action": "create",
            "title": "Two files",
            "visibility": "internal",
            "files": [
                {"file_path": "a.py", "content": "a = 1"},
                {"file_path": "b.py", "content": "b = 2", "action": "create"},
            ],
        },
        "POST",
        "/snippets",
        body={
            "visibility": "internal",
            "title": "Two files",
            "files": [
                {"file_path": "a.py", "content": "a = 1"},
                {"file_path": "b.py", "content": "b = 2"},
            ],
        },
        response=StubResponse(status=201, json={"id": 5}),
    ),
    Case(
        "gitlab_snippets",
        {
            "action": "update",
            "snippet_id": 5,
            "files": [
                {"action": "move", "file_path": "c.py", "previous_path": "b.py"},
                {"action": "delete", "file_path": "a.py"},
            ],
        },
        "PUT",
        "/snippets/5",
        body={
            "files": [
                {"action": "move", "file_path": "c.py", "previous_path": "b.py"},
                {"action": "delete", "file_path": "a.py"},
            ]
        },
    ),
    Case(
        "gitlab_snippets",
        {"action": "update", "project": "grp/app", "snippet_id": 21, "visibility": "public"},
        "PUT",
        SNIPPET,
        body={"visibility": "public"},
    ),
    Case(
        "gitlab_snippets",
        {"action": "delete", "project": "grp/app", "snippet_id": 21},
        "DELETE",
        SNIPPET,
        response=StubResponse(status=204),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def succeed(stub: GitLabStub, tool: str, arguments: dict[str, Any]) -> Any:
    outcome = await call(stub, tool, arguments)
    assert outcome.is_error is False, outcome.structured
    return outcome.structured


async def fail(stub: GitLabStub, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    outcome = await call(stub, tool, arguments)
    assert outcome.is_error is True, outcome.structured
    error: dict[str, Any] = outcome.structured["error"]
    return error


# gitlab_members


async def test_roles_come_back_by_name_as_well_as_number() -> None:
    stub = GitLabStub()
    levels = [10, 15, 20, 25, 30, 40, 50, 5, 99]
    stub.add(
        "GET",
        f"{P}/members",
        StubResponse(
            json=[{"id": index, "access_level": level} for index, level in enumerate(levels)]
        ),
    )
    result = await succeed(stub, "gitlab_members", {"action": "list", "project": "grp/app"})
    names = [member.get("access_level_name") for member in result["items"]]
    assert names == [
        "guest",
        "planner",
        "reporter",
        "security_manager",
        "developer",
        "maintainer",
        "owner",
        "minimal_access",
        None,
    ]
    assert [member["access_level"] for member in result["items"]] == levels


@pytest.mark.parametrize("role", ["maintainer", 40])
async def test_a_role_is_given_by_name_or_by_number(role: str | int) -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{P}/members/7", StubResponse(json={**MEMBER, "access_level": 40}))
    result = await succeed(
        stub,
        "gitlab_members",
        {
            "action": "update",
            "project": "grp/app",
            "user_id": 7,
            "access_level": role,
            "confirm": True,
        },
    )
    assert body_of(stub.requests[0]) == {"access_level": 40}
    assert result["access_level_name"] == "maintainer"


@pytest.mark.parametrize("role", ["admin", "Developer", 35, 60])
async def test_only_real_roles_are_accepted(role: str | int) -> None:
    stub = GitLabStub()
    error = await fail(
        stub,
        "gitlab_members",
        {"action": "add", "project": "grp/app", "user_id": 7, "access_level": role},
    )
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


@pytest.mark.parametrize("who", [{}, {"user_id": 7, "username": "ada"}])
async def test_add_names_exactly_one_user(who: dict[str, Any]) -> None:
    stub = GitLabStub()
    error = await fail(
        stub,
        "gitlab_members",
        {"action": "add", "project": "grp/app", "access_level": "guest", **who},
    )
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


@pytest.mark.parametrize(
    "arguments", [{"action": "update", "access_level": "guest"}, {"action": "remove"}]
)
async def test_changing_or_removing_a_member_needs_confirmation(arguments: dict[str, Any]) -> None:
    stub = GitLabStub()
    error = await fail(stub, "gitlab_members", {"project": "grp/app", "user_id": 7, **arguments})
    assert error["code"] == "confirmation_required"
    assert stub.requests == []


@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("PUT", {"action": "update", "access_level": "guest", "confirm": True}),
        ("DELETE", {"action": "remove", "confirm": True}),
    ],
)
async def test_an_inherited_member_cannot_be_changed_here_and_the_error_says_why(
    method: str, arguments: dict[str, Any]
) -> None:
    stub = GitLabStub()
    stub.add(method, f"{P}/members/7", StubResponse(status=404, json={"message": "404 Not found"}))
    error = await fail(stub, "gitlab_members", {"project": "grp/app", "user_id": 7, **arguments})
    assert error["code"] == "gitlab_not_found"
    assert "parent group" in error["message"]
    assert "list_group_members" in error["details"]["hint"]


async def test_a_missing_direct_member_points_to_inherited_access() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/members/7", StubResponse(status=404, json={"message": "404 Not found"}))
    error = await fail(
        stub, "gitlab_members", {"action": "get", "project": "grp/app", "user_id": 7}
    )
    assert "inherited" in error["details"]["hint"]


async def test_a_missing_member_with_inherited_access_gets_no_hint() -> None:
    # The hint says to try inherited access, which this call already did.
    stub = GitLabStub()
    stub.add(
        "GET", f"{P}/members/all/7", StubResponse(status=404, json={"message": "404 Not found"})
    )
    arguments = {"action": "get", "project": "grp/app", "user_id": 7, "inherited": True}
    error = await fail(stub, "gitlab_members", arguments)
    assert error["code"] == "gitlab_not_found"
    assert "hint" not in error["details"]


@pytest.mark.parametrize("who", [{}, {"user_id": 7, "username": "ada"}])
async def test_get_user_names_exactly_one_user(who: dict[str, Any]) -> None:
    stub = GitLabStub()
    error = await fail(stub, "gitlab_users", {"action": "get", **who})
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_adding_an_existing_member_points_to_update() -> None:
    stub = GitLabStub()
    stub.add(
        "POST", f"{P}/members", StubResponse(status=409, json={"message": "Member already exists"})
    )
    error = await fail(
        stub,
        "gitlab_members",
        {"action": "add", "project": "grp/app", "user_id": 7, "access_level": "reporter"},
    )
    assert error["code"] == "gitlab_conflict"
    assert "use update" in error["message"]


# gitlab_users


async def test_who_am_i_describes_the_token_without_revealing_it() -> None:
    stub = GitLabStub()
    stub.add("GET", "/user", StubResponse(json={"id": 1, "username": "me"}))
    stub.add(
        "GET",
        "/personal_access_tokens/self",
        StubResponse(
            json={
                "id": 9,
                "name": "laptop",
                "scopes": ["api"],
                "expires_at": "2026-12-31",
                "active": True,
                "user_id": 1,
                "token": "glpat-should-never-appear",
            }
        ),
    )
    result = await succeed(stub, "gitlab_users", {"action": "get_current"})
    assert result == {
        "id": 1,
        "username": "me",
        "token_info": {
            "name": "laptop",
            "scopes": ["api"],
            "expires_at": "2026-12-31",
            "active": True,
        },
    }


async def test_who_am_i_still_answers_when_gitlab_hides_the_token_details() -> None:
    stub = GitLabStub()
    stub.add("GET", "/user", StubResponse(json={"id": 1, "username": "me"}))
    stub.add("GET", "/personal_access_tokens/self", StubResponse(status=403, json={}))
    result = await succeed(stub, "gitlab_users", {"action": "get_current"})
    assert result == {"id": 1, "username": "me"}


async def test_a_user_is_found_by_username() -> None:
    stub = GitLabStub()
    stub.add("GET", "/users", StubResponse(json=[{"id": 7, "username": "ada"}]))
    stub.add("GET", "/users/7", StubResponse(json={"id": 7, "username": "ada", "bio": "hi"}))
    result = await succeed(stub, "gitlab_users", {"action": "get", "username": "ada"})
    assert result["bio"] == "hi"
    assert dict(stub.requests[0].url.params) == {"username": "ada"}


async def test_an_unknown_username_is_not_found() -> None:
    stub = GitLabStub()
    stub.add("GET", "/users", LIST)
    error = await fail(stub, "gitlab_users", {"action": "get", "username": "nobody"})
    assert error["code"] == "gitlab_not_found"
    assert "nobody" in error["message"]


async def test_a_read_user_token_is_offered_user_lookup_only() -> None:
    views = ToolRegistry(TOOLSETS).visible(request_context(), frozenset({"read_user"}))
    assert [view.tool.name for view in views] == ["gitlab_users"]
    assert [action.name for action in views[0].actions] == ["get_current", "get", "search"]


# gitlab_wikis


async def test_update_keeps_the_page_format_gitlab_would_reset() -> None:
    stub = GitLabStub()
    page = f"{P}/wikis/docs%2Fsetup"
    stub.add("GET", page, StubResponse(json={"slug": "docs/setup", "format": "asciidoc"}))
    stub.add("PUT", page, StubResponse(json={"slug": "docs/setup", "format": "asciidoc"}))
    await succeed(
        stub,
        "gitlab_wikis",
        {"action": "update", "project": "grp/app", "slug": "docs/setup", "content": "= Setup"},
    )
    assert body_of(stub.requests[-1]) == {"content": "= Setup", "format": "asciidoc"}


async def test_a_new_title_reports_where_the_page_moved() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{P}/wikis/docs%2Fsetup", StubResponse(json={"slug": "docs/Install"}))
    result = await succeed(
        stub,
        "gitlab_wikis",
        {
            "action": "update",
            "project": "grp/app",
            "slug": "docs/setup",
            "title": "docs/Install",
            "format": "markdown",
        },
    )
    assert "docs/Install" in result["note"]


async def test_a_wiki_update_needs_a_change() -> None:
    stub = GitLabStub()
    error = await fail(
        stub, "gitlab_wikis", {"action": "update", "project": "grp/app", "slug": "home"}
    )
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_wiki_content_is_listed_only_on_request() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/wikis", LIST)
    await succeed(
        stub, "gitlab_wikis", {"action": "list", "project": "grp/app", "with_content": True}
    )
    assert dict(stub.requests[0].url.params) == {"with_content": "true"}


# gitlab_webhooks

LEAKY_HOOK = {
    "id": 3,
    "url": HOOK_URL,
    "token": SECRET,
    "signing_token": "whsec_c2VjcmV0",
    "custom_headers": [{"key": "Authorization", "value": "Bearer header-secret"}],
    "url_variables": {"tenant": "variable-secret"},
    "token_present": True,
}


@pytest.mark.parametrize(
    ("method", "path", "arguments"),
    [
        ("GET", f"{P}/hooks", {"action": "list"}),
        ("GET", f"{P}/hooks/3", {"action": "get", "hook_id": 3}),
        ("POST", f"{P}/hooks", {"action": "create", "url": HOOK_URL}),
        ("PUT", f"{P}/hooks/3", {"action": "update", "hook_id": 3, "name": "CI"}),
    ],
)
async def test_webhook_secrets_never_come_back(
    method: str, path: str, arguments: dict[str, Any]
) -> None:
    stub = GitLabStub()
    listed = arguments["action"] == "list"
    stub.add(method, path, StubResponse(json=[LEAKY_HOOK] if listed else LEAKY_HOOK))
    result = await succeed(stub, "gitlab_webhooks", {"project": "grp/app", **arguments})
    shown = str(result)
    for secret in (SECRET, "whsec_", "header-secret", "variable-secret"):
        assert secret not in shown
    hook = result["items"][0] if listed else result
    assert hook["custom_headers"] == [{"key": "Authorization"}]
    assert hook["url_variables"] == [{"key": "tenant"}]
    assert hook["token_present"] is True


async def test_custom_headers_in_an_unexpected_shape_are_never_shown() -> None:
    # If GitLab ever sent the headers some other way, show nothing rather than their values.
    stub = GitLabStub()
    hook = {"id": 3, "custom_headers": "Authorization: Bearer header-secret"}
    stub.add("GET", f"{P}/hooks/3", StubResponse(json=hook))
    result = await succeed(
        stub, "gitlab_webhooks", {"action": "get", "project": "grp/app", "hook_id": 3}
    )
    assert result["custom_headers"] == []
    assert "header-secret" not in str(result)


async def test_the_secret_token_reaches_gitlab_but_not_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = GitLabStub()
    stub.add("POST", f"{P}/hooks", StubResponse(status=201, json={"id": 3}))
    with caplog.at_level(logging.DEBUG):
        await succeed(
            stub,
            "gitlab_webhooks",
            {"action": "create", "project": "grp/app", "url": HOOK_URL, "token": SECRET},
        )
    assert body_of(stub.requests[0])["token"] == SECRET
    assert caplog.records
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert SECRET not in str(record.__dict__)


@pytest.mark.parametrize(
    ("arguments", "response", "warned"),
    [
        ({"url": "https://new.example.com"}, {"id": 3}, True),
        ({"url": "https://new.example.com"}, {"id": 3, "token_present": False}, True),
        ({"url": "https://new.example.com"}, {"id": 3, "token_present": True}, False),
        ({"url": "https://new.example.com", "token": "again"}, {"id": 3}, False),
        ({"name": "CI"}, {"id": 3}, False),
    ],
)
async def test_a_new_url_warns_that_gitlab_drops_the_token(
    arguments: dict[str, Any], response: dict[str, Any], warned: bool
) -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{P}/hooks/3", StubResponse(json=response))
    result = await succeed(
        stub,
        "gitlab_webhooks",
        {"action": "update", "project": "grp/app", "hook_id": 3, **arguments},
    )
    assert ("secret token" in result.get("note", "")) is warned


@pytest.mark.parametrize(("confirmed", "warned"), [(True, False), (None, True)])
async def test_an_unconfirmed_signing_token_is_flagged(
    confirmed: bool | None, warned: bool
) -> None:
    stub = GitLabStub()
    response = {"id": 3} if confirmed is None else {"id": 3, "signing_token_present": confirmed}
    stub.add("POST", f"{P}/hooks", StubResponse(status=201, json=response))
    result = await succeed(
        stub,
        "gitlab_webhooks",
        {
            "action": "create",
            "project": "grp/app",
            "url": HOOK_URL,
            "signing_token": "whsec_" + "A" * 43 + "=",
        },
    )
    assert ("19.0" in result.get("note", "")) is warned


async def test_a_webhook_update_needs_a_change() -> None:
    stub = GitLabStub()
    error = await fail(
        stub, "gitlab_webhooks", {"action": "update", "project": "grp/app", "hook_id": 3}
    )
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_a_failed_test_event_says_what_may_be_wrong() -> None:
    stub = GitLabStub()
    stub.add(
        "POST",
        f"{P}/hooks/3/test/push_events",
        StubResponse(status=422, json={"message": "Ensure the project has commits."}),
    )
    error = await fail(
        stub,
        "gitlab_webhooks",
        {"action": "test", "project": "grp/app", "hook_id": 3, "trigger": "push_events"},
    )
    assert error["code"] == "gitlab_unprocessable"
    assert "Ensure the project has commits." in error["message"]
    assert "receiver" in error["details"]["hint"]


async def test_only_events_gitlab_can_sample_are_offered_for_testing() -> None:
    stub = GitLabStub()
    error = await fail(
        stub,
        "gitlab_webhooks",
        {"action": "test", "project": "grp/app", "hook_id": 3, "trigger": "deployment_events"},
    )
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_expires_at_and_clear_expiry_cannot_both_be_given() -> None:
    stub = GitLabStub()
    arguments = {
        "action": "update",
        "project": "grp/app",
        "user_id": 7,
        "access_level": "developer",
        "expires_at": "2026-12-31",
        "clear_expiry": True,
        "confirm": True,
    }
    error = await fail(stub, "gitlab_members", arguments)
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_custom_headers_follow_a_url_change_in_a_second_update() -> None:
    # GitLab clears custom headers when the URL changes, even within the request setting them.
    stub = GitLabStub()
    stub.add("PUT", f"{P}/hooks/3", StubResponse(json={"id": 3}))
    headers = [{"key": "Authorization", "value": SECRET}]
    arguments = {
        "action": "update",
        "project": "grp/app",
        "hook_id": 3,
        "url": "https://new.example.com",
        "custom_headers": headers,
    }
    await succeed(stub, "gitlab_webhooks", arguments)
    assert [body_of(request) for request in stub.requests] == [
        {"url": "https://new.example.com"},
        {"custom_headers": headers},
    ]


async def test_custom_headers_alone_take_one_update() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{P}/hooks/3", StubResponse(json={"id": 3}))
    headers = [{"key": "X-Env", "value": "prod"}]
    arguments = {"action": "update", "project": "grp/app", "hook_id": 3, "custom_headers": headers}
    await succeed(stub, "gitlab_webhooks", arguments)
    assert [body_of(request) for request in stub.requests] == [{"custom_headers": headers}]


@pytest.mark.parametrize(
    ("arguments", "response", "warned"),
    [
        ({"url": "https://new.example.com"}, {"id": 3, "custom_headers": []}, True),
        ({"url": "https://new.example.com"}, {"id": 3, "custom_headers": [{"key": "A"}]}, False),
        (
            {"url": "https://new.example.com", "custom_headers": [{"key": "A", "value": "b"}]},
            {"id": 3},
            False,
        ),
        ({"name": "CI"}, {"id": 3}, False),
    ],
)
async def test_a_new_url_warns_that_gitlab_drops_custom_headers(
    arguments: dict[str, Any], response: dict[str, Any], warned: bool
) -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{P}/hooks/3", StubResponse(json=response))
    result = await succeed(
        stub,
        "gitlab_webhooks",
        {"action": "update", "project": "grp/app", "hook_id": 3, **arguments},
    )
    assert ("custom headers" in result.get("note", "")) is warned


@pytest.mark.parametrize("action", ["set_custom_header", "set_url_variable"])
async def test_header_and_variable_values_reach_gitlab_but_not_the_caller_or_logs(
    action: str, caplog: pytest.LogCaptureFixture
) -> None:
    kind = "custom_headers" if action == "set_custom_header" else "url_variables"
    stub = GitLabStub()
    stub.add("PUT", f"{P}/hooks/3/{kind}/Token", StubResponse(status=204))
    arguments = {
        "action": action,
        "project": "grp/app",
        "hook_id": 3,
        "key": "Token",
        "value": SECRET,
    }
    with caplog.at_level(logging.DEBUG):
        result = await succeed(stub, "gitlab_webhooks", arguments)
    assert body_of(stub.requests[0]) == {"value": SECRET}
    assert SECRET not in str(result)
    for record in caplog.records:
        assert SECRET not in str(record.__dict__)


# gitlab_snippets


async def test_snippet_content_that_is_not_utf8_comes_back_as_base64() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{SNIPPET}/raw", StubResponse(content=b"\xff\xfe"))
    arguments = {"action": "get_content", "project": "grp/app", "snippet_id": 21}
    result = await succeed(stub, "gitlab_snippets", arguments)
    assert result["encoding"] == "base64"
    assert result["content"] == "//4="


async def test_an_oversized_snippet_file_is_refused() -> None:
    from mcp_gitlab.config import Settings

    stub = GitLabStub()
    stub.add("GET", "/snippets/5/files/v1/big.txt/raw", StubResponse(content=b"x" * 64))
    arguments = {"action": "get_content", "snippet_id": 5, "file_path": "big.txt", "ref": "v1"}
    outcome = await call(stub, "gitlab_snippets", arguments, Settings(gitlab_mcp_max_file_bytes=16))
    error = outcome.structured["error"]
    assert error["code"] == "payload_too_large"
    assert error["message"].startswith("'big.txt' ")
    assert "GITLAB_MCP_MAX_FILE_BYTES" in error["message"]
    assert "smaller file" in error["message"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "list", "project": "grp/app", "scope": "all"},
        {"action": "create", "title": "t"},
        {"action": "create", "title": "t", "content": "x"},
        {
            "action": "create",
            "title": "t",
            "content": "x",
            "file_name": "x",
            "files": [{"file_path": "a", "content": "a"}],
        },
        {
            "action": "create",
            "title": "t",
            "file_name": "x",
            "files": [{"file_path": "a", "content": "a"}],
        },
        {"action": "create", "title": "t", "files": [{"file_path": "a"}]},
        {
            "action": "create",
            "title": "t",
            "files": [{"file_path": "a", "content": "a", "action": "delete"}],
        },
        {"action": "update", "snippet_id": 5},
        {"action": "update", "snippet_id": 5, "files": [{"file_path": "a", "content": "a"}]},
        {"action": "update", "snippet_id": 5, "files": [{"file_path": "a", "action": "move"}]},
        {
            "action": "update",
            "snippet_id": 5,
            "content": "x",
            "files": [{"file_path": "a", "action": "delete"}],
        },
    ],
)
async def test_snippet_arguments_are_checked_before_calling_gitlab(
    arguments: dict[str, Any],
) -> None:
    stub = GitLabStub()
    error = await fail(stub, "gitlab_snippets", arguments)
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []
