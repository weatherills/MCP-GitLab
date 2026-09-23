"""PRD-04 toolset `issues`: gitlab_issues, gitlab_issue_notes, gitlab_labels, gitlab_milestones."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
G = "/groups/grp"
ISSUE = f"{P}/issues/34"
REF = {"project": "grp/app", "issue_iid": 34}
PAGE = {"page": "1", "per_page": "20"}

CASES = [
    Case(
        "gitlab_issues",
        {"action": "list", "project": "grp/app", "labels": ["bug"], "milestone": "1.0"},
        "GET",
        f"{P}/issues",
        {**PAGE, "state": "opened", "labels": "bug", "milestone": "1.0"},
        response=LIST,
    ),
    Case("gitlab_issues", {"action": "get", **REF}, "GET", ISSUE),
    Case(
        "gitlab_issues",
        {
            "action": "create",
            "project": "grp/app",
            "title": "Login fails",
            "description": "Steps...",
            "labels": ["bug", "p1"],
            "assignee_ids": [7],
            "milestone_id": 3,
            "due_date": "2026-10-01",
        },
        "POST",
        f"{P}/issues",
        body={
            "title": "Login fails",
            "description": "Steps...",
            "labels": "bug,p1",
            "assignee_ids": [7],
            "milestone_id": 3,
            "due_date": "2026-10-01",
        },
        response=StubResponse(status=201, json={"iid": 34}),
    ),
    Case(
        "gitlab_issues",
        {"action": "update", **REF, "labels": [], "confidential": True},
        "PUT",
        ISSUE,
        body={"labels": "", "confidential": True},
    ),
    Case("gitlab_issues", {"action": "close", **REF}, "PUT", ISSUE, body={"state_event": "close"}),
    Case(
        "gitlab_issues", {"action": "reopen", **REF}, "PUT", ISSUE, body={"state_event": "reopen"}
    ),
    Case(
        "gitlab_issues",
        {"action": "delete", **REF, "confirm": True},
        "DELETE",
        ISSUE,
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_issues",
        {"action": "move", **REF, "to_project": 99},
        "POST",
        f"{ISSUE}/move",
        body={"to_project_id": 99},
        response=StubResponse(status=201, json={"iid": 1, "project_id": 99}),
    ),
    Case("gitlab_issues", {"action": "list_links", **REF}, "GET", f"{ISSUE}/links", response=LIST),
    Case(
        "gitlab_issues",
        {"action": "link", **REF, "target_project": "grp/app", "target_issue_iid": 12},
        "POST",
        f"{ISSUE}/links",
        body={"target_project_id": "grp/app", "target_issue_iid": 12},
        response=StubResponse(status=201, json={"source_issue": {}, "target_issue": {}}),
    ),
    Case(
        "gitlab_issues",
        {"action": "unlink", **REF, "issue_link_id": 5},
        "DELETE",
        f"{ISSUE}/links/5",
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "list_discussions", **REF},
        "GET",
        f"{ISSUE}/discussions",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "create_discussion", **REF, "body": "Can you reproduce?"},
        "POST",
        f"{ISSUE}/discussions",
        body={"body": "Can you reproduce?"},
        response=StubResponse(status=201, json={"id": "d1"}),
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "reply_discussion", **REF, "discussion_id": "d1", "body": "Yes."},
        "POST",
        f"{ISSUE}/discussions/d1/notes",
        body={"body": "Yes."},
        response=StubResponse(status=201, json={"id": 8}),
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "list_notes", **REF, "activity_filter": "only_comments"},
        "GET",
        f"{ISSUE}/notes",
        {**PAGE, "activity_filter": "only_comments"},
        response=LIST,
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "create_note", **REF, "body": "Fixed in !12."},
        "POST",
        f"{ISSUE}/notes",
        body={"body": "Fixed in !12."},
        response=StubResponse(status=201, json={"id": 9}),
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "update_note", **REF, "note_id": 8, "discussion_id": "d1", "body": "Yes!"},
        "PUT",
        f"{ISSUE}/discussions/d1/notes/8",
        body={"body": "Yes!"},
    ),
    Case(
        "gitlab_issue_notes",
        {"action": "delete_note", **REF, "note_id": 9},
        "DELETE",
        f"{ISSUE}/notes/9",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_labels",
        {"action": "list", "project": "grp/app", "search": "bug"},
        "GET",
        f"{P}/labels",
        {**PAGE, "search": "bug"},
        response=LIST,
    ),
    Case(
        "gitlab_labels",
        {"action": "get", "project": "grp/app", "label": "needs review"},
        "GET",
        f"{P}/labels/needs%20review",
    ),
    Case(
        "gitlab_labels",
        {"action": "create", "project": "grp/app", "name": "p1", "color": "#D9534F", "priority": 1},
        "POST",
        f"{P}/labels",
        body={"name": "p1", "color": "#D9534F", "priority": 1},
        response=StubResponse(status=201, json={"id": 4}),
    ),
    Case(
        "gitlab_labels",
        {"action": "update", "project": "grp/app", "label": 4, "new_name": "priority::1"},
        "PUT",
        f"{P}/labels/4",
        body={"new_name": "priority::1"},
    ),
    Case(
        "gitlab_labels",
        {"action": "delete", "project": "grp/app", "label": 4},
        "DELETE",
        f"{P}/labels/4",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_milestones",
        {"action": "list", "project": "grp/app", "state": "active"},
        "GET",
        f"{P}/milestones",
        {**PAGE, "state": "active"},
        response=LIST,
    ),
    Case(
        "gitlab_milestones",
        {"action": "get", "project": "grp/app", "milestone_id": 3},
        "GET",
        f"{P}/milestones/3",
    ),
    Case(
        "gitlab_milestones",
        {"action": "create", "project": "grp/app", "title": "1.0", "due_date": "2026-12-01"},
        "POST",
        f"{P}/milestones",
        body={"title": "1.0", "due_date": "2026-12-01"},
        response=StubResponse(status=201, json={"id": 3}),
    ),
    Case(
        "gitlab_milestones",
        {"action": "update", "project": "grp/app", "milestone_id": 3, "state_event": "close"},
        "PUT",
        f"{P}/milestones/3",
        body={"state_event": "close"},
    ),
    Case(
        "gitlab_milestones",
        {"action": "delete", "project": "grp/app", "milestone_id": 3},
        "DELETE",
        f"{P}/milestones/3",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_milestones",
        {"action": "list_issues", "project": "grp/app", "milestone_id": 3},
        "GET",
        f"{P}/milestones/3/issues",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_milestones",
        {"action": "list_merge_requests", "project": "grp/app", "milestone_id": 3},
        "GET",
        f"{P}/milestones/3/merge_requests",
        PAGE,
        response=LIST,
    ),
    # A group's own labels and milestones.
    Case(
        "gitlab_labels",
        {"action": "list", "group": "grp", "with_counts": True},
        "GET",
        f"{G}/labels",
        {**PAGE, "with_counts": "true"},
        response=LIST,
    ),
    Case(
        "gitlab_labels",
        {"action": "get", "group": 7, "label": "bug"},
        "GET",
        "/groups/7/labels/bug",
    ),
    Case(
        "gitlab_labels",
        {"action": "create", "group": "grp", "name": "team::web", "color": "#0033CC"},
        "POST",
        f"{G}/labels",
        body={"name": "team::web", "color": "#0033CC"},
        response=StubResponse(status=201, json={"id": 11}),
    ),
    Case(
        "gitlab_labels",
        {"action": "update", "group": "grp", "label": "team::web", "description": "Web team"},
        "PUT",
        f"{G}/labels/team%3A%3Aweb",
        body={"description": "Web team"},
    ),
    Case(
        "gitlab_labels",
        {"action": "delete", "group": "grp", "label": 11},
        "DELETE",
        f"{G}/labels/11",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_milestones",
        {"action": "list", "project": "grp/app", "include_ancestors": True},
        "GET",
        f"{P}/milestones",
        {**PAGE, "include_ancestors": "true"},
        response=LIST,
    ),
    Case(
        "gitlab_milestones",
        {"action": "list", "group": "grp", "search": "2026"},
        "GET",
        f"{G}/milestones",
        {**PAGE, "search": "2026"},
        response=LIST,
    ),
    Case(
        "gitlab_milestones",
        {"action": "get", "group": "grp", "milestone_id": 8},
        "GET",
        f"{G}/milestones/8",
    ),
    Case(
        "gitlab_milestones",
        {"action": "create", "group": "grp", "title": "Q4", "start_date": "2026-10-01"},
        "POST",
        f"{G}/milestones",
        body={"title": "Q4", "start_date": "2026-10-01"},
        response=StubResponse(status=201, json={"id": 8}),
    ),
    Case(
        "gitlab_milestones",
        {"action": "update", "group": "grp", "milestone_id": 8, "due_date": "2026-12-31"},
        "PUT",
        f"{G}/milestones/8",
        body={"due_date": "2026-12-31"},
    ),
    Case(
        "gitlab_milestones",
        {"action": "delete", "group": "grp", "milestone_id": 8},
        "DELETE",
        f"{G}/milestones/8",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_milestones",
        {"action": "list_issues", "group": "grp", "milestone_id": 8},
        "GET",
        f"{G}/milestones/8/issues",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_milestones",
        {"action": "list_merge_requests", "group": "grp", "milestone_id": 8},
        "GET",
        f"{G}/milestones/8/merge_requests",
        PAGE,
        response=LIST,
    ),
    # Time tracking.
    Case("gitlab_issues", {"action": "get_time_stats", **REF}, "GET", f"{ISSUE}/time_stats"),
    Case(
        "gitlab_issues",
        {"action": "set_time_estimate", **REF, "duration": "1d4h"},
        "POST",
        f"{ISSUE}/time_estimate",
        body={"duration": "1d4h"},
    ),
    Case(
        "gitlab_issues",
        {"action": "reset_time_estimate", **REF},
        "POST",
        f"{ISSUE}/reset_time_estimate",
    ),
    Case(
        "gitlab_issues",
        {"action": "add_spent_time", **REF, "duration": "-30m"},
        "POST",
        f"{ISSUE}/add_spent_time",
        body={"duration": "-30m"},
        response=StubResponse(status=201, json={"total_time_spent": 5400}),
    ),
    Case(
        "gitlab_issues", {"action": "reset_spent_time", **REF}, "POST", f"{ISSUE}/reset_spent_time"
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def test_listing_every_state_leaves_the_state_filter_off() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/issues", LIST)
    await call(stub, "gitlab_issues", {"action": "list", "project": "grp/app", "state": "all"})
    assert "state" not in stub.requests[-1].url.params


async def test_delete_requires_confirmation() -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_issues", {"action": "delete", **REF})
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


async def test_a_forbidden_delete_explains_who_may_delete() -> None:
    stub = GitLabStub()
    stub.add("DELETE", ISSUE, StubResponse(status=403, json={"message": "403 Forbidden"}))
    outcome = await call(stub, "gitlab_issues", {"action": "delete", **REF, "confirm": True})
    error = outcome.structured["error"]
    assert error["code"] == "gitlab_forbidden"
    assert "Owner" in error["message"]
    assert "Consider close instead" in error["details"]["hint"]


async def test_move_resolves_a_target_path_to_its_id() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/grp%2Fother", StubResponse(json={"id": 55}))
    stub.add("POST", f"{ISSUE}/move", StubResponse(status=201, json={"iid": 1}))
    await call(stub, "gitlab_issues", {"action": "move", **REF, "to_project": "grp/other"})
    assert body_of(stub.requests[-1]) == {"to_project_id": 55}


async def test_a_new_label_needs_a_color() -> None:
    outcome = await call(
        GitLabStub(), "gitlab_labels", {"action": "create", "project": "grp/app", "name": "p1"}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gitlab_issues", {"action": "update", **REF}),
        ("gitlab_labels", {"action": "update", "project": "grp/app", "label": 4}),
        ("gitlab_milestones", {"action": "update", "project": "grp/app", "milestone_id": 3}),
    ],
)
async def test_updates_need_a_change(tool: str, arguments: dict[str, object]) -> None:
    outcome = await call(GitLabStub(), tool, arguments)
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_dates_must_be_iso_formatted() -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_milestones",
        {"action": "create", "project": "grp/app", "title": "1.0", "due_date": "01/12/2026"},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


def test_issue_threads_cannot_be_resolved() -> None:
    from mcp_gitlab.toolsets.issues.notes import ISSUE_NOTES_TOOL

    assert ISSUE_NOTES_TOOL.action("resolve_discussion") is None


@pytest.mark.parametrize("tool", ["gitlab_labels", "gitlab_milestones"])
@pytest.mark.parametrize("owner", [{}, {"project": "grp/app", "group": "grp"}])
async def test_labels_and_milestones_belong_to_a_project_or_a_group(
    tool: str, owner: dict[str, object]
) -> None:
    stub = GitLabStub()
    outcome = await call(stub, tool, {"action": "list", **owner})
    error = outcome.structured["error"]
    assert error["code"] == "invalid_arguments"
    assert "exactly one of project or group" in str(error["details"]["problems"])
    assert stub.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "create", "name": "p1", "color": "red", "priority": 1},
        {"action": "update", "label": "p1", "priority": 1},
    ],
)
async def test_group_labels_have_no_priority(arguments: dict[str, object]) -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_labels", {**arguments, "group": "grp"})
    error = outcome.structured["error"]
    assert error["code"] == "invalid_arguments"
    assert "group labels have none" in str(error["details"]["problems"])
    assert stub.requests == []


@pytest.mark.parametrize(
    ("arguments", "method"),
    [
        ({"action": "update", "label": "bug", "color": "red"}, "PUT"),
        ({"action": "delete", "label": "bug"}, "DELETE"),
    ],
)
async def test_an_inherited_label_is_changed_through_its_group(
    arguments: dict[str, object], method: str
) -> None:
    # GitLab lists a group's labels for its projects, but finds only the project's own by ID.
    stub = GitLabStub()
    stub.add(
        method, f"{P}/labels/bug", StubResponse(status=404, json={"message": "404 Label Not Found"})
    )
    outcome = await call(stub, "gitlab_labels", {**arguments, "project": "grp/app"})
    error = outcome.structured["error"]
    assert error["code"] == "gitlab_not_found"
    assert "give group instead of project" in error["details"]["hint"]


async def test_a_missing_group_label_gets_no_hint() -> None:
    stub = GitLabStub()
    stub.add(
        "DELETE",
        f"{G}/labels/bug",
        StubResponse(status=404, json={"message": "404 Label Not Found"}),
    )
    outcome = await call(
        stub, "gitlab_labels", {"action": "delete", "group": "grp", "label": "bug"}
    )
    assert "hint" not in outcome.structured["error"]["details"]


async def test_a_missing_project_gets_no_label_hint() -> None:
    stub = GitLabStub()
    stub.add(
        "PUT",
        f"{P}/labels/bug",
        StubResponse(status=404, json={"message": "404 Project Not Found"}),
    )
    arguments = {"action": "update", "project": "grp/app", "label": "bug", "color": "red"}
    outcome = await call(stub, "gitlab_labels", arguments)
    assert "hint" not in outcome.structured["error"]["details"]


@pytest.mark.parametrize(
    ("action", "method", "suffix"),
    [
        ("get", "GET", ""),
        ("update", "PUT", ""),
        ("delete", "DELETE", ""),
        ("list_issues", "GET", "/issues"),
        ("list_merge_requests", "GET", "/merge_requests"),
    ],
)
async def test_an_inherited_milestone_is_reached_through_its_group(
    action: str, method: str, suffix: str
) -> None:
    stub = GitLabStub()
    stub.add(
        method,
        f"{P}/milestones/8{suffix}",
        StubResponse(status=404, json={"message": "404 Not found"}),
    )
    arguments = {"action": action, "project": "grp/app", "milestone_id": 8}
    if action == "update":
        arguments["title"] = "Q4"
    outcome = await call(stub, "gitlab_milestones", arguments)
    error = outcome.structured["error"]
    assert error["code"] == "gitlab_not_found"
    assert "give group instead of project" in error["details"]["hint"]


@pytest.mark.parametrize(
    ("owner", "path", "message"),
    [
        ({"project": "grp/app"}, f"{P}/milestones/8", "404 Project Not Found"),
        ({"group": "grp"}, f"{G}/milestones/8", "404 Not found"),
    ],
)
async def test_other_missing_milestones_get_no_hint(
    owner: dict[str, object], path: str, message: str
) -> None:
    stub = GitLabStub()
    stub.add("GET", path, StubResponse(status=404, json={"message": message}))
    outcome = await call(stub, "gitlab_milestones", {"action": "get", "milestone_id": 8, **owner})
    assert "hint" not in outcome.structured["error"]["details"]
