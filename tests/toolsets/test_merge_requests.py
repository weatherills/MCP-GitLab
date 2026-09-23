"""PRD-03 toolset `merge_requests`: gitlab_merge_requests and gitlab_mr_reviews."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
MR = f"{P}/merge_requests/12"
REF = {"project": "grp/app", "merge_request_iid": 12}
DIFF_REFS = {"base_sha": "b" * 40, "head_sha": "h" * 40, "start_sha": "s" * 40}

CASES = [
    Case(
        "gitlab_merge_requests",
        {
            "action": "list",
            "project": "grp/app",
            "state": "opened",
            "target_branch": "main",
            "labels": ["bug", "ui"],
        },
        "GET",
        f"{P}/merge_requests",
        {
            "page": "1",
            "per_page": "20",
            "state": "opened",
            "target_branch": "main",
            "labels": "bug,ui",
        },
        response=LIST,
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "get", **REF, "include_rebase_in_progress": True},
        "GET",
        MR,
        {"include_rebase_in_progress": "true"},
    ),
    Case(
        "gitlab_merge_requests",
        {
            "action": "create",
            "project": "grp/app",
            "source_branch": "feature/login",
            "target_branch": "main",
            "title": "Add login",
            "description": "Adds the login page.",
            "labels": ["feature"],
            "assignee_ids": [7],
            "remove_source_branch": True,
        },
        "POST",
        f"{P}/merge_requests",
        body={
            "source_branch": "feature/login",
            "target_branch": "main",
            "title": "Add login",
            "description": "Adds the login page.",
            "labels": "feature",
            "assignee_ids": [7],
            "remove_source_branch": True,
        },
        response=StubResponse(status=201, json={"iid": 12}),
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "update", **REF, "title": "Add login page", "target_branch": "develop"},
        "PUT",
        MR,
        body={"title": "Add login page", "target_branch": "develop"},
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "close", **REF},
        "PUT",
        MR,
        body={"state_event": "close"},
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "reopen", **REF},
        "PUT",
        MR,
        body={"state_event": "reopen"},
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "get_diff", **REF},
        "GET",
        f"{MR}/diffs",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "list_commits", **REF},
        "GET",
        f"{MR}/commits",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "merge", **REF, "squash": True, "sha": "abc123", "confirm": True},
        "PUT",
        f"{MR}/merge",
        body={"squash": True, "sha": "abc123"},
        response=StubResponse(json={"iid": 12, "state": "merged"}),
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "rebase", **REF, "skip_ci": True},
        "PUT",
        f"{MR}/rebase",
        body={"skip_ci": True},
        response=StubResponse(status=202, json={"rebase_in_progress": True}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "list_discussions", **REF},
        "GET",
        f"{MR}/discussions",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "create_discussion", **REF, "body": "Why?"},
        "POST",
        f"{MR}/discussions",
        body={"body": "Why?"},
        response=StubResponse(status=201, json={"id": "d1"}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "reply_discussion", **REF, "discussion_id": "d1", "body": "Because."},
        "POST",
        f"{MR}/discussions/d1/notes",
        body={"body": "Because."},
        response=StubResponse(status=201, json={"id": 5}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "resolve_discussion", **REF, "discussion_id": "d1"},
        "PUT",
        f"{MR}/discussions/d1",
        body={"resolved": True},
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "list_notes", **REF, "sort": "asc"},
        "GET",
        f"{MR}/notes",
        {"page": "1", "per_page": "20", "sort": "asc"},
        response=LIST,
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "create_note", **REF, "body": "LGTM", "internal": True},
        "POST",
        f"{MR}/notes",
        body={"body": "LGTM", "internal": True},
        response=StubResponse(status=201, json={"id": 6}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "update_note", **REF, "note_id": 6, "body": "LGTM!"},
        "PUT",
        f"{MR}/notes/6",
        body={"body": "LGTM!"},
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "delete_note", **REF, "note_id": 6},
        "DELETE",
        f"{MR}/notes/6",
        response=StubResponse(status=204),
    ),
    Case("gitlab_mr_reviews", {"action": "list_approvals", **REF}, "GET", f"{MR}/approvals"),
    Case(
        "gitlab_mr_reviews",
        {"action": "approve", **REF, "sha": "abc123"},
        "POST",
        f"{MR}/approve",
        body={"sha": "abc123"},
        response=StubResponse(status=201, json={"approved": True}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "unapprove", **REF},
        "POST",
        f"{MR}/unapprove",
        response=StubResponse(status=201, json={}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "list_approval_rules", **REF},
        "GET",
        f"{MR}/approval_rules",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_merge_requests",
        {
            "action": "merge",
            **REF,
            "squash": True,
            "squash_commit_message": "Add login (#12)",
            "merge_commit_message": "Merge login",
            "confirm": True,
        },
        "PUT",
        f"{MR}/merge",
        body={
            "squash": True,
            "squash_commit_message": "Add login (#12)",
            "merge_commit_message": "Merge login",
        },
    ),
    Case("gitlab_merge_requests", {"action": "get_time_stats", **REF}, "GET", f"{MR}/time_stats"),
    Case(
        "gitlab_merge_requests",
        {"action": "set_time_estimate", **REF, "duration": "3h30m"},
        "POST",
        f"{MR}/time_estimate",
        body={"duration": "3h30m"},
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "reset_time_estimate", **REF},
        "POST",
        f"{MR}/reset_time_estimate",
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "add_spent_time", **REF, "duration": "45m", "summary": "Review"},
        "POST",
        f"{MR}/add_spent_time",
        body={"duration": "45m", "summary": "Review"},
    ),
    Case(
        "gitlab_merge_requests",
        {"action": "reset_spent_time", **REF},
        "POST",
        f"{MR}/reset_spent_time",
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "list_reviewers", **REF},
        "GET",
        f"{MR}/reviewers",
        {"page": "1", "per_page": "20"},
        response=LIST,
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "list_draft_notes", **REF},
        "GET",
        f"{MR}/draft_notes",
        response=LIST,
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "create_draft_note", **REF, "body": "Why not reuse the helper?"},
        "POST",
        f"{MR}/draft_notes",
        body={"note": "Why not reuse the helper?"},
        response=StubResponse(status=201, json={"id": 5}),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "update_draft_note", **REF, "draft_note_id": 5, "body": "Reuse the helper."},
        "PUT",
        f"{MR}/draft_notes/5",
        body={"note": "Reuse the helper."},
        setup=(("GET", f"{MR}/draft_notes/5", StubResponse(json={"id": 5, "position": {}})),),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "delete_draft_note", **REF, "draft_note_id": 5},
        "DELETE",
        f"{MR}/draft_notes/5",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "publish_draft_note", **REF, "draft_note_id": 5},
        "PUT",
        f"{MR}/draft_notes/5/publish",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_mr_reviews",
        {"action": "publish_review", **REF},
        "POST",
        f"{MR}/draft_notes/bulk_publish",
        response=StubResponse(status=204),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def test_create_as_draft_prefixes_the_title() -> None:
    stub = GitLabStub()
    stub.add("POST", f"{P}/merge_requests", StubResponse(status=201, json={"iid": 12}))
    await call(
        stub,
        "gitlab_merge_requests",
        {
            "action": "create",
            "project": "grp/app",
            "source_branch": "f",
            "target_branch": "main",
            "title": "Add login",
            "draft": True,
        },
    )
    body = body_of(stub.requests[-1])
    assert body["title"] == "Draft: Add login"
    assert "draft" not in body


@pytest.mark.parametrize("current", ["Draft: Add login", "[Draft] Add login", "(draft) Add login"])
async def test_marking_ready_strips_any_draft_marker(current: str) -> None:
    stub = GitLabStub()
    stub.add("GET", MR, StubResponse(json={"iid": 12, "title": current}))
    stub.add("PUT", MR, StubResponse(json={"iid": 12}))
    await call(stub, "gitlab_merge_requests", {"action": "update", **REF, "draft": False})
    assert body_of(stub.requests[-1]) == {"title": "Add login"}


async def test_update_needs_a_change() -> None:
    outcome = await call(GitLabStub(), "gitlab_merge_requests", {"action": "update", **REF})
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_get_diff_summarizes_and_flags_oversized_files() -> None:
    diffs = [
        {"old_path": "a.py", "new_path": "a.py", "diff": "@@ -1 +1,2 @@\n-x\n+y\n+z\n"},
        {"old_path": "big.sql", "new_path": "big.sql", "diff": "", "too_large": True},
    ]
    stub = GitLabStub()
    stub.add("GET", f"{MR}/diffs", StubResponse(json=diffs))
    outcome = await call(
        stub,
        "gitlab_merge_requests",
        {"action": "get_diff", **REF, "include_diff_for": ["a.py"]},
    )
    first, second = outcome.structured["items"]
    assert (first["additions"], first["deletions"], first["diff"]) == (2, 1, diffs[0]["diff"])
    assert second["too_large"] is True and "diff" not in second


async def test_auto_merge_also_sends_the_pre_17_11_flag() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{MR}/merge", StubResponse(json={"iid": 12}))
    await call(
        stub,
        "gitlab_merge_requests",
        {"action": "merge", **REF, "auto_merge": True, "confirm": True},
    )
    assert body_of(stub.requests[-1]) == {"auto_merge": True, "merge_when_pipeline_succeeds": True}


async def test_merge_requires_confirmation() -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_merge_requests", {"action": "merge", **REF})
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


@pytest.mark.parametrize(
    ("detailed_status", "code", "retryable", "advice"),
    [
        ("need_rebase", "merge_blocked", False, "rebase"),
        ("conflict", "merge_blocked", False, "conflicts"),
        ("discussions_not_resolved", "merge_blocked", False, "resolve_discussion"),
        ("ci_still_running", "merge_pending", True, "auto_merge"),
        ("some_new_policy", "merge_blocked", False, "some_new_policy"),
    ],
)
async def test_a_refused_merge_says_why_and_what_to_do(
    detailed_status: str, code: str, retryable: bool, advice: str
) -> None:
    stub = GitLabStub()
    stub.add(
        "PUT", f"{MR}/merge", StubResponse(status=405, json={"message": "405 Method Not Allowed"})
    )
    stub.add(
        "GET",
        MR,
        StubResponse(
            json={
                "detailed_merge_status": detailed_status,
                "has_conflicts": detailed_status == "conflict",
                "head_pipeline": {"status": "running"},
            }
        ),
    )
    outcome = await call(stub, "gitlab_merge_requests", {"action": "merge", **REF, "confirm": True})
    error = outcome.structured["error"]
    assert (error["code"], error["retryable"]) == (code, retryable)
    assert error["details"]["detailed_merge_status"] == detailed_status
    assert error["details"]["pipeline_status"] == "running"
    assert advice in error["details"]["next_step"]


async def test_a_moved_source_branch_is_reported_as_such() -> None:
    stub = GitLabStub()
    stub.add(
        "PUT",
        f"{MR}/merge",
        StubResponse(status=409, json={"message": "SHA does not match HEAD of source branch"}),
    )
    outcome = await call(
        stub, "gitlab_merge_requests", {"action": "merge", **REF, "sha": "old", "confirm": True}
    )
    error = outcome.structured["error"]
    assert error["code"] == "merge_blocked"
    assert "newer than sha old" in error["message"]


async def test_other_merge_failures_pass_through() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{MR}/merge", StubResponse(status=403, json={"message": "403 Forbidden"}))
    outcome = await call(stub, "gitlab_merge_requests", {"action": "merge", **REF, "confirm": True})
    assert outcome.structured["error"]["code"] == "gitlab_forbidden"


async def test_rebase_explains_how_to_follow_it() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{MR}/rebase", StubResponse(status=202, json={"rebase_in_progress": True}))
    outcome = await call(stub, "gitlab_merge_requests", {"action": "rebase", **REF})
    assert outcome.structured["rebase_in_progress"] is True
    assert "include_rebase_in_progress" in outcome.structured["note"]


async def test_a_diff_comment_is_anchored_to_the_current_diff() -> None:
    stub = GitLabStub()
    stub.add("GET", MR, StubResponse(json={"iid": 12, "diff_refs": DIFF_REFS}))
    stub.add("POST", f"{MR}/discussions", StubResponse(status=201, json={"id": "d2"}))
    await call(
        stub,
        "gitlab_mr_reviews",
        {
            "action": "create_discussion",
            **REF,
            "body": "Off by one?",
            "file_path": "src/app.py",
            "new_line": 14,
        },
    )
    assert body_of(stub.requests[-1]) == {
        "body": "Off by one?",
        "position": {
            "position_type": "text",
            **DIFF_REFS,
            "new_path": "src/app.py",
            "old_path": "src/app.py",
            "new_line": 14,
        },
    }


async def test_a_diff_comment_waits_for_gitlab_to_compute_the_diff() -> None:
    stub = GitLabStub()
    stub.add("GET", MR, StubResponse(json={"iid": 12, "diff_refs": None}))
    outcome = await call(
        stub,
        "gitlab_mr_reviews",
        {"action": "create_discussion", **REF, "body": "x", "file_path": "a.py", "old_line": 3},
    )
    assert outcome.structured["error"]["code"] == "diff_not_ready"
    assert outcome.structured["error"]["retryable"] is True


@pytest.mark.parametrize(
    "position",
    [{"file_path": "a.py"}, {"new_line": 3}, {"old_path": "b.py", "new_line": 3}],
)
async def test_a_diff_position_must_be_complete(position: dict[str, object]) -> None:
    outcome = await call(
        GitLabStub(),
        "gitlab_mr_reviews",
        {"action": "create_discussion", **REF, "body": "x", **position},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_thread_replies_are_edited_through_their_thread() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{MR}/discussions/d1/notes/5", StubResponse(json={"id": 5}))
    stub.add("DELETE", f"{MR}/discussions/d1/notes/5", StubResponse(status=204))
    await call(
        stub,
        "gitlab_mr_reviews",
        {"action": "update_note", **REF, "note_id": 5, "discussion_id": "d1", "body": "Edited"},
    )
    await call(
        stub,
        "gitlab_mr_reviews",
        {"action": "delete_note", **REF, "note_id": 5, "discussion_id": "d1"},
    )
    assert [request.method for request in stub.requests] == ["PUT", "DELETE"]


async def test_approval_rules_on_gitlab_free_explain_the_tier() -> None:
    stub = GitLabStub()
    stub.add(
        "GET", f"{MR}/approval_rules", StubResponse(status=404, json={"message": "404 Not Found"})
    )
    outcome = await call(stub, "gitlab_mr_reviews", {"action": "list_approval_rules", **REF})
    error = outcome.structured["error"]
    assert error["code"] == "gitlab_not_found"
    assert "Premium" in error["message"]
    assert "list_approvals" in error["details"]["hint"]


async def test_a_draft_on_a_diff_line_is_anchored_to_the_current_diff() -> None:
    stub = GitLabStub()
    stub.add("GET", MR, StubResponse(json={"diff_refs": DIFF_REFS}))
    stub.add("POST", f"{MR}/draft_notes", StubResponse(status=201, json={"id": 6}))
    arguments = {"file_path": "app.py", "new_line": 7, "body": "Off by one?"}
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "create_draft_note", **REF, **arguments}
    )
    assert outcome.is_error is False
    assert body_of(stub.requests[-1]) == {
        "note": "Off by one?",
        "position": {
            "position_type": "text",
            **DIFF_REFS,
            "new_path": "app.py",
            "old_path": "app.py",
            "new_line": 7,
        },
    }


async def test_a_draft_reply_can_resolve_its_thread() -> None:
    stub = GitLabStub()
    stub.add("POST", f"{MR}/draft_notes", StubResponse(status=201, json={"id": 7}))
    arguments = {"discussion_id": "abc", "resolve_discussion": True, "body": "Fixed."}
    await call(stub, "gitlab_mr_reviews", {"action": "create_draft_note", **REF, **arguments})
    assert body_of(stub.requests[0]) == {
        "note": "Fixed.",
        "in_reply_to_discussion_id": "abc",
        "resolve_discussion": True,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"discussion_id": "abc", "file_path": "app.py", "new_line": 3},
        {"resolve_discussion": True},
        {"file_path": "app.py"},
        {"old_path": "old.py", "new_line": 3},
    ],
)
async def test_a_draft_note_must_say_where_it_goes(arguments: dict[str, object]) -> None:
    stub = GitLabStub()
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "create_draft_note", **REF, "body": "x", **arguments}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_editing_a_draft_keeps_it_on_its_diff_line() -> None:
    # GitLab drops a draft's position unless the update sends it again.
    position = {
        "position_type": "text",
        **DIFF_REFS,
        "old_path": "app.py",
        "new_path": "app.py",
        "old_line": None,
        "new_line": 7,
        "line_range": None,
    }
    stub = GitLabStub()
    stub.add("GET", f"{MR}/draft_notes/6", StubResponse(json={"id": 6, "position": position}))
    stub.add("PUT", f"{MR}/draft_notes/6", StubResponse(json={"id": 6}))
    arguments = {"draft_note_id": 6, "body": "Off by one."}
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "update_draft_note", **REF, **arguments}
    )
    assert outcome.is_error is False
    assert body_of(stub.requests[-1]) == {
        "note": "Off by one.",
        "position": {
            "position_type": "text",
            **DIFF_REFS,
            "old_path": "app.py",
            "new_path": "app.py",
            "new_line": 7,
        },
    }


async def test_a_review_summary_is_posted_as_a_comment_after_the_drafts() -> None:
    # bulk_publish takes a summary only from GitLab 19.2; earlier versions drop it silently.
    stub = GitLabStub()
    stub.add("POST", f"{MR}/draft_notes/bulk_publish", StubResponse(status=204))
    stub.add("POST", f"{MR}/notes", StubResponse(status=201, json={"id": 40}))
    arguments = {"body": "Two small things, otherwise good.", "internal": True}
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "publish_review", **REF, **arguments}
    )
    assert stub.paths() == [f"/api/v4{MR}/draft_notes/bulk_publish", f"/api/v4{MR}/notes"]
    assert body_of(stub.requests[0]) is None
    assert body_of(stub.requests[1]) == {
        "body": "Two small things, otherwise good.",
        "internal": True,
    }
    assert outcome.structured == {"published_review": 12, "summary": {"id": 40}}


async def test_a_summary_that_fails_says_the_drafts_were_published() -> None:
    stub = GitLabStub()
    stub.add("POST", f"{MR}/draft_notes/bulk_publish", StubResponse(status=204))
    stub.add("POST", f"{MR}/notes", StubResponse(status=403, json={"message": "403 Forbidden"}))
    arguments = {"body": "Looks good."}
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "publish_review", **REF, **arguments}
    )
    error = outcome.structured["error"]
    assert error["code"] == "gitlab_forbidden"
    assert "drafts were published" in error["message"]


async def test_internal_applies_only_to_a_summary() -> None:
    stub = GitLabStub()
    arguments = {"internal": True}
    outcome = await call(
        stub, "gitlab_mr_reviews", {"action": "publish_review", **REF, **arguments}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_an_instance_that_requires_sha_says_so() -> None:
    stub = GitLabStub()
    stub.add("PUT", f"{MR}/merge", StubResponse(status=400, json={"message": "sha is missing"}))
    outcome = await call(stub, "gitlab_merge_requests", {"action": "merge", **REF, "confirm": True})
    error = outcome.structured["error"]
    assert error["code"] == "merge_blocked"
    assert "requires sha" in error["message"]


async def test_a_refusal_is_passed_through_when_the_merge_request_cannot_be_read() -> None:
    stub = GitLabStub()
    stub.add(
        "PUT", f"{MR}/merge", StubResponse(status=405, json={"message": "405 Method Not Allowed"})
    )
    stub.add("GET", MR, StubResponse(status=403, json={"message": "403 Forbidden"}))
    outcome = await call(stub, "gitlab_merge_requests", {"action": "merge", **REF, "confirm": True})
    error = outcome.structured["error"]
    assert error["code"] != "merge_blocked"
    assert error["details"]["status"] == 405 if "status" in error["details"] else True
