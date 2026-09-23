"""PRD-01 toolset `projects`: gitlab_projects, gitlab_branches, gitlab_tags, gitlab_badges."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"

CASES = [
    Case(
        "gitlab_projects",
        {"action": "list", "search": "api", "owned": True},
        "GET",
        "/projects",
        {"page": "1", "per_page": "20", "search": "api", "owned": "true", "simple": "true"},
        response=LIST,
    ),
    Case("gitlab_projects", {"action": "get", "project": "grp/app"}, "GET", P),
    Case("gitlab_projects", {"action": "get", "project": 42}, "GET", "/projects/42"),
    Case(
        "gitlab_projects",
        {"action": "create", "name": "App", "namespace": 7, "initialize_with_readme": True},
        "POST",
        "/projects",
        body={"name": "App", "namespace_id": 7, "initialize_with_readme": True},
    ),
    Case(
        "gitlab_projects",
        {"action": "update", "project": "grp/app", "description": "New", "merge_method": "ff"},
        "PUT",
        P,
        body={"description": "New", "merge_method": "ff"},
    ),
    Case(
        "gitlab_projects",
        {"action": "delete", "project": "grp/app", "confirm": True},
        "DELETE",
        P,
        response=StubResponse(status=202, json={"message": "202 Accepted"}),
    ),
    Case(
        "gitlab_projects",
        {"action": "fork", "project": "grp/app", "namespace": "me/sandbox", "name": "App fork"},
        "POST",
        f"{P}/fork",
        body={"name": "App fork", "namespace_path": "me/sandbox"},
    ),
    Case("gitlab_projects", {"action": "archive", "project": "grp/app"}, "POST", f"{P}/archive"),
    Case(
        "gitlab_projects", {"action": "unarchive", "project": "grp/app"}, "POST", f"{P}/unarchive"
    ),
    Case("gitlab_projects", {"action": "star", "project": "grp/app"}, "POST", f"{P}/star"),
    Case("gitlab_projects", {"action": "unstar", "project": "grp/app"}, "POST", f"{P}/unstar"),
    Case(
        "gitlab_projects",
        {"action": "list_forks", "project": "grp/app"},
        "GET",
        f"{P}/forks",
        {"page": "1", "per_page": "20", "simple": "true"},
        response=LIST,
    ),
    Case(
        "gitlab_branches",
        {"action": "list", "project": "grp/app", "search": "^feat"},
        "GET",
        f"{P}/repository/branches",
        {"page": "1", "per_page": "20", "search": "^feat"},
        response=LIST,
    ),
    Case(
        "gitlab_branches",
        {"action": "get", "project": "grp/app", "branch": "feature/login"},
        "GET",
        f"{P}/repository/branches/feature%2Flogin",
    ),
    Case(
        "gitlab_branches",
        {"action": "create", "project": "grp/app", "branch": "feature/login", "ref": "main"},
        "POST",
        f"{P}/repository/branches",
        body={"branch": "feature/login", "ref": "main"},
    ),
    Case(
        "gitlab_branches",
        {"action": "delete", "project": "grp/app", "branch": "feature/login", "confirm": True},
        "DELETE",
        f"{P}/repository/branches/feature%2Flogin",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_branches",
        {"action": "delete_merged", "project": "grp/app", "confirm": True},
        "DELETE",
        f"{P}/repository/merged_branches",
        response=StubResponse(status=202, json={"message": "202 Accepted"}),
    ),
    Case(
        "gitlab_branches",
        {
            "action": "protect",
            "project": "grp/app",
            "branch": "release/*",
            "push_access_level": "no_access",
            "merge_access_level": "developer",
            "allow_force_push": False,
        },
        "POST",
        f"{P}/protected_branches",
        body={
            "name": "release/*",
            "push_access_level": 0,
            "merge_access_level": 30,
            "allow_force_push": False,
        },
    ),
    Case(
        "gitlab_branches",
        {"action": "unprotect", "project": "grp/app", "branch": "release/*"},
        "DELETE",
        f"{P}/protected_branches/release%2F%2A",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_branches",
        {"action": "list_protected", "project": "grp/app"},
        "GET",
        f"{P}/protected_branches",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_tags",
        {"action": "list", "project": "grp/app", "order_by": "version", "sort": "desc"},
        "GET",
        f"{P}/repository/tags",
        {"page": "1", "per_page": "20", "order_by": "version", "sort": "desc"},
        response=LIST,
    ),
    Case(
        "gitlab_tags",
        {"action": "get", "project": "grp/app", "tag": "v1.2.0"},
        "GET",
        f"{P}/repository/tags/v1.2.0",
    ),
    Case(
        "gitlab_tags",
        {
            "action": "create",
            "project": "grp/app",
            "tag": "v1.2.0",
            "ref": "main",
            "message": "1.2",
        },
        "POST",
        f"{P}/repository/tags",
        body={"tag_name": "v1.2.0", "ref": "main", "message": "1.2"},
    ),
    Case(
        "gitlab_tags",
        {"action": "delete", "project": "grp/app", "tag": "v1.2.0"},
        "DELETE",
        f"{P}/repository/tags/v1.2.0",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_tags",
        {
            "action": "protect",
            "project": "grp/app",
            "tag": "v*",
            "create_access_level": "maintainer",
        },
        "POST",
        f"{P}/protected_tags",
        body={"name": "v*", "create_access_level": 40},
    ),
    Case(
        "gitlab_tags",
        {"action": "unprotect", "project": "grp/app", "tag": "v*"},
        "DELETE",
        f"{P}/protected_tags/v%2A",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_tags",
        {"action": "list_protected", "project": "grp/app"},
        "GET",
        f"{P}/protected_tags",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    # A lightweight tag, and protection at GitLab's default levels: nothing unset is sent.
    Case(
        "gitlab_tags",
        {"action": "create", "project": "grp/app", "tag": "v1.2.1", "ref": "main"},
        "POST",
        f"{P}/repository/tags",
        body={"tag_name": "v1.2.1", "ref": "main"},
    ),
    Case(
        "gitlab_tags",
        {"action": "protect", "project": "grp/app", "tag": "v*"},
        "POST",
        f"{P}/protected_tags",
        body={"name": "v*"},
    ),
    Case(
        "gitlab_branches",
        {"action": "protect", "project": "grp/app", "branch": "main"},
        "POST",
        f"{P}/protected_branches",
        body={"name": "main"},
    ),
    # A namespace given as a numeric string is an ID, so no lookup is made.
    Case(
        "gitlab_projects",
        {"action": "create", "path": "svc", "namespace": "314"},
        "POST",
        "/projects",
        body={"path": "svc", "namespace_id": 314, "initialize_with_readme": False},
    ),
    Case(
        "gitlab_projects",
        {"action": "fork", "project": "grp/app", "namespace": 314},
        "POST",
        f"{P}/fork",
        body={"namespace_id": 314},
    ),
    Case(
        "gitlab_projects",
        {"action": "get", "project": "grp/app", "statistics": True, "license": True},
        "GET",
        P,
        {"statistics": "true", "license": "true"},
    ),
    Case(
        "gitlab_projects",
        {"action": "get_languages", "project": "grp/app"},
        "GET",
        f"{P}/languages",
        response=StubResponse(json={"Python": 91.5, "Shell": 8.5}),
    ),
    Case(
        "gitlab_projects",
        {"action": "create", "name": "Site", "template_name": "plainhtml"},
        "POST",
        "/projects",
        body={"name": "Site", "initialize_with_readme": False, "template_name": "plainhtml"},
    ),
    Case(
        "gitlab_projects",
        {"action": "transfer", "project": "grp/app", "namespace": "platform", "confirm": True},
        "PUT",
        f"{P}/transfer",
        body={"namespace": "platform"},
        response=StubResponse(json={"id": 9, "namespace": {"id": 5, "full_path": "platform"}}),
    ),
    Case(
        "gitlab_projects",
        {"action": "list_transfer_locations", "project": "grp/app", "search": "plat"},
        "GET",
        f"{P}/transfer_locations",
        {"page": "1", "per_page": "20", "search": "plat"},
        response=LIST,
    ),
    Case(
        "gitlab_badges",
        {"action": "list", "project": "grp/app", "name": "coverage"},
        "GET",
        f"{P}/badges",
        {"page": "1", "per_page": "20", "name": "coverage"},
        response=LIST,
    ),
    Case(
        "gitlab_badges",
        {"action": "get", "project": "grp/app", "badge_id": 3},
        "GET",
        f"{P}/badges/3",
    ),
    Case(
        "gitlab_badges",
        {
            "action": "create",
            "project": "grp/app",
            "link_url": "https://gitlab.example.com/%{project_path}/-/pipelines",
            "image_url": "https://gitlab.example.com/%{project_path}/badges/%{default_branch}/pipeline.svg",
            "name": "pipeline",
        },
        "POST",
        f"{P}/badges",
        body={
            "link_url": "https://gitlab.example.com/%{project_path}/-/pipelines",
            "image_url": "https://gitlab.example.com/%{project_path}/badges/%{default_branch}/pipeline.svg",
            "name": "pipeline",
        },
        response=StubResponse(status=201, json={"id": 3}),
    ),
    Case(
        "gitlab_badges",
        {"action": "update", "project": "grp/app", "badge_id": 3, "name": "ci"},
        "PUT",
        f"{P}/badges/3",
        body={"name": "ci"},
    ),
    Case(
        "gitlab_badges",
        {"action": "delete", "project": "grp/app", "badge_id": 3},
        "DELETE",
        f"{P}/badges/3",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_badges",
        {
            "action": "preview",
            "project": "grp/app",
            "link_url": "https://ci.example.com/%{project_path}",
            "image_url": "https://ci.example.com/%{project_path}/badge.svg",
        },
        "GET",
        f"{P}/badges/render",
        {
            "link_url": "https://ci.example.com/%{project_path}",
            "image_url": "https://ci.example.com/%{project_path}/badge.svg",
        },
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def test_create_resolves_a_namespace_path_to_its_id() -> None:
    stub = GitLabStub()
    stub.add("GET", "/namespaces/grp%2Fteam", StubResponse(json={"id": 314, "kind": "group"}))
    stub.add("POST", "/projects", StubResponse(status=201, json={"id": 9}))
    outcome = await call(
        stub, "gitlab_projects", {"action": "create", "path": "svc", "namespace": "grp/team"}
    )
    assert outcome.structured == {"id": 9}
    body = body_of(stub.requests[-1])
    assert body == {"path": "svc", "namespace_id": 314, "initialize_with_readme": False}
    assert "visibility" not in body  # unset, so the instance's own default applies


async def test_delete_reports_the_retention_date() -> None:
    stub = GitLabStub()
    stub.add("DELETE", P, StubResponse(status=202, json={"message": "202 Accepted"}))
    stub.add("GET", P, StubResponse(json={"id": 9, "marked_for_deletion_on": "2026-10-22"}))
    outcome = await call(
        stub, "gitlab_projects", {"action": "delete", "project": "grp/app", "confirm": True}
    )
    assert outcome.structured["status"] == "marked_for_deletion"
    assert outcome.structured["marked_for_deletion_on"] == "2026-10-22"
    assert "2026-10-22" in outcome.structured["note"]


async def test_delete_without_retention_reports_deleted() -> None:
    stub = GitLabStub()
    stub.add("DELETE", P, StubResponse(status=202, json={"message": "202 Accepted"}))
    outcome = await call(
        stub, "gitlab_projects", {"action": "delete", "project": "grp/app", "confirm": True}
    )  # the read-back gets GitLab's 404
    assert outcome.structured["status"] == "deleted"


async def test_delete_succeeds_even_if_the_read_back_fails() -> None:
    stub = GitLabStub()
    stub.add("DELETE", P, StubResponse(status=202, json={"message": "202 Accepted"}))
    stub.add("GET", P, StubResponse(status=403, json={"message": "403 Forbidden"}))
    outcome = await call(
        stub, "gitlab_projects", {"action": "delete", "project": "grp/app", "confirm": True}
    )
    assert outcome.is_error is False
    assert outcome.structured["status"] == "deletion_requested"


async def test_create_needs_a_name_or_path() -> None:
    outcome = await call(
        GitLabStub(), "gitlab_projects", {"action": "create", "visibility": "private"}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_update_needs_a_change() -> None:
    outcome = await call(GitLabStub(), "gitlab_projects", {"action": "update", "project": 1})
    assert outcome.structured["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gitlab_projects", {"action": "delete", "project": 1}),
        ("gitlab_branches", {"action": "delete", "project": 1, "branch": "old"}),
        ("gitlab_branches", {"action": "delete_merged", "project": 1}),
    ],
)
async def test_destructive_actions_require_confirmation(
    tool: str, arguments: dict[str, object]
) -> None:
    stub = GitLabStub()
    outcome = await call(stub, tool, arguments)
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


async def test_star_reports_an_unchanged_star() -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects/1/star", StubResponse(status=304))
    outcome = await call(stub, "gitlab_projects", {"action": "star", "project": 1})
    assert outcome.structured == {"starred": True, "changed": False}


async def test_unknown_access_level_is_rejected() -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_branches",
        {"action": "protect", "project": 1, "branch": "main", "push_access_level": "owner"},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_blank_project_is_rejected() -> None:
    outcome = await call(GitLabStub(), "gitlab_projects", {"action": "get", "project": ""})
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_transfer_reports_a_move_gitlab_has_only_queued() -> None:
    stub = GitLabStub()
    moving = {"id": 9, "namespace": {"id": 2, "full_path": "grp"}}  # still in its old group
    stub.add("PUT", f"{P}/transfer", StubResponse(json=moving))
    outcome = await call(
        stub,
        "gitlab_projects",
        {"action": "transfer", "project": "grp/app", "namespace": 5, "confirm": True},
    )
    assert outcome.structured["status"] == "queued"
    assert "background" in outcome.structured["note"]
    assert body_of(stub.requests[0]) == {"namespace": "5"}


async def test_transfer_by_id_recognises_the_completed_move() -> None:
    stub = GitLabStub()
    moved = {"id": 9, "namespace": {"id": 5, "full_path": "platform"}}
    stub.add("PUT", f"{P}/transfer", StubResponse(json=moved))
    outcome = await call(
        stub,
        "gitlab_projects",
        {"action": "transfer", "project": "grp/app", "namespace": 5, "confirm": True},
    )
    assert outcome.structured == {"status": "transferred", "project": moved}


async def test_transfer_requires_confirmation() -> None:
    stub = GitLabStub()
    outcome = await call(
        stub, "gitlab_projects", {"action": "transfer", "project": 1, "namespace": "platform"}
    )
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


async def test_badge_update_needs_a_change() -> None:
    outcome = await call(
        GitLabStub(), "gitlab_badges", {"action": "update", "project": 1, "badge_id": 3}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"
