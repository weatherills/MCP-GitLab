"""PRD-07 toolset `search`: gitlab_search at instance, group, and project level."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, call

LIST = StubResponse(json=[])
PAGE = {"page": "1", "per_page": "20"}

CASES = [
    Case(
        "gitlab_search",
        {"action": "global", "scope": "projects", "search": "billing"},
        "GET",
        "/search",
        {**PAGE, "scope": "projects", "search": "billing"},
        response=LIST,
    ),
    Case(
        "gitlab_search",
        {
            "action": "group",
            "group": "grp/team",
            "scope": "issues",
            "search": "crash",
            "state": "opened",
        },
        "GET",
        "/groups/grp%2Fteam/search",
        {**PAGE, "scope": "issues", "search": "crash", "state": "opened"},
        response=LIST,
    ),
    Case(
        "gitlab_search",
        {
            "action": "project",
            "project": "grp/app",
            "scope": "blobs",
            "search": "def login",
            "ref": "dev",
        },
        "GET",
        "/projects/grp%2Fapp/search",
        {**PAGE, "scope": "blobs", "search": "def login", "ref": "dev"},
        response=LIST,
    ),
]


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{case.id}-{case.arguments['scope']}" for case in CASES]
)
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def search(stub: GitLabStub, **arguments: object) -> dict[str, object]:
    outcome = await call(stub, "gitlab_search", arguments)
    return outcome.structured


async def test_results_are_compact() -> None:
    issue = {
        "id": 1,
        "iid": 34,
        "project_id": 9,
        "title": "Login fails",
        "description": "long body " * 100,
        "state": "opened",
        "labels": ["bug"],
        "author": {"id": 7, "username": "alice", "avatar_url": "https://..."},
        "web_url": "https://gitlab.example.com/grp/app/-/issues/34",
        "time_stats": {"time_estimate": 0},
    }
    stub = GitLabStub()
    stub.add("GET", "/search", StubResponse(json=[issue]))
    result = await search(stub, action="global", scope="issues", search="login")
    assert result["items"] == [
        {
            "id": 1,
            "iid": 34,
            "project_id": 9,
            "title": "Login fails",
            "state": "opened",
            "labels": ["bug"],
            "author": "alice",
            "web_url": "https://gitlab.example.com/grp/app/-/issues/34",
        }
    ]


async def test_long_text_is_truncated() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/1/search",
        StubResponse(json=[{"id": 5, "body": "x" * 1000, "noteable_type": "Issue"}]),
    )
    result = await search(stub, action="project", project=1, scope="notes", search="x")
    body = result["items"][0]["body"]  # type: ignore[index]
    assert len(body) == 301 and body.endswith("…")


async def test_code_search_across_projects_explains_advanced_search() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/search",
        StubResponse(status=400, json={"message": "400 Bad request - Scope not supported"}),
    )
    outcome = await call(
        stub, "gitlab_search", {"action": "global", "scope": "blobs", "search": "TODO"}
    )
    error = outcome.structured["error"]
    assert error["code"] == "advanced_search_unavailable"
    assert "project action" in error["message"]
    assert error["details"]["scope"] == "blobs"


async def test_an_empty_cross_project_code_search_carries_a_caveat() -> None:
    stub = GitLabStub()
    stub.add("GET", "/groups/5/search", LIST)
    result = await search(stub, action="group", group=5, scope="commits", search="fix")
    assert result["items"] == []
    assert "Advanced Search" in str(result["note"])


async def test_an_empty_project_search_has_no_caveat() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/1/search", LIST)
    result = await search(stub, action="project", project=1, scope="blobs", search="zzz")
    assert "note" not in result


async def test_other_bad_requests_pass_through() -> None:
    stub = GitLabStub()
    stub.add("GET", "/search", StubResponse(status=400, json={"message": "search is too short"}))
    outcome = await call(
        stub, "gitlab_search", {"action": "global", "scope": "projects", "search": "a"}
    )
    assert outcome.structured["error"]["code"] == "gitlab_bad_request"


@pytest.mark.parametrize(
    ("action", "scope", "where"),
    [
        ("project", "projects", {"project": 1}),
        ("project", "groups", {"project": 1}),
        ("group", "snippet_titles", {"group": 5}),
    ],
)
async def test_each_level_accepts_only_its_scopes(
    action: str, scope: str, where: dict[str, object]
) -> None:
    stub = GitLabStub()
    outcome = await call(
        stub, "gitlab_search", {"action": action, "scope": scope, "search": "x", **where}
    )
    error = outcome.structured["error"]
    assert error["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_state_all_leaves_the_filter_off() -> None:
    stub = GitLabStub()
    stub.add("GET", "/search", LIST)
    await search(stub, action="global", scope="merge_requests", search="x", state="all")
    assert "state" not in stub.requests[-1].url.params
