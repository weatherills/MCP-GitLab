"""PRD-04 toolset `issues`: gitlab_issues, gitlab_issue_notes, gitlab_labels, gitlab_milestones."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
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
