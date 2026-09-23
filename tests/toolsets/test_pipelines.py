"""PRD-05 toolset `pipelines`: gitlab_pipelines, gitlab_jobs, gitlab_ci_variables,
gitlab_pipeline_schedules, gitlab_runners."""

import base64

import pytest

from mcp_gitlab.config import Settings
from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
PIPE = f"{P}/pipelines/77"
JOB = f"{P}/jobs/5"
PAGE = {"page": "1", "per_page": "20"}
SCHEDULE = f"{P}/pipeline_schedules/13"
SECRET = "s3cr3t-value-never-shown"
VARIABLE = {
    "key": "DEPLOY_TOKEN",
    "value": SECRET,
    "protected": True,
    "masked": True,
    "environment_scope": "*",
    "variable_type": "env_var",
}
SCHEDULE_VARIABLE = {"key": "TARGET", "value": SECRET, "variable_type": "env_var"}
SCHEDULE_DETAILS = {"id": 13, "cron": "0 2 * * *", "variables": [SCHEDULE_VARIABLE]}

CASES = [
    Case(
        "gitlab_pipelines",
        {"action": "list", "project": "grp/app", "status": "failed", "ref": "main"},
        "GET",
        f"{P}/pipelines",
        {**PAGE, "status": "failed", "ref": "main"},
        response=LIST,
    ),
    Case(
        "gitlab_pipelines", {"action": "get", "project": "grp/app", "pipeline_id": 77}, "GET", PIPE
    ),
    Case(
        "gitlab_pipelines",
        {
            "action": "create",
            "project": "grp/app",
            "ref": "main",
            "variables": [{"key": "DEPLOY", "value": "false"}],
        },
        "POST",
        f"{P}/pipeline",
        body={"ref": "main", "variables": [{"key": "DEPLOY", "value": "false"}]},
        response=StubResponse(status=201, json={"id": 78, "status": "created"}),
    ),
    Case(
        "gitlab_pipelines",
        {"action": "retry", "project": "grp/app", "pipeline_id": 77},
        "POST",
        f"{PIPE}/retry",
        response=StubResponse(status=201, json={"id": 77, "status": "pending"}),
    ),
    Case(
        "gitlab_pipelines",
        {"action": "cancel", "project": "grp/app", "pipeline_id": 77},
        "POST",
        f"{PIPE}/cancel",
        response=StubResponse(json={"id": 77, "status": "canceled"}),
    ),
    Case(
        "gitlab_pipelines",
        {"action": "delete", "project": "grp/app", "pipeline_id": 77, "confirm": True},
        "DELETE",
        PIPE,
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_jobs",
        {"action": "list", "project": "grp/app", "pipeline_id": 77, "include_retried": True},
        "GET",
        f"{PIPE}/jobs",
        {**PAGE, "include_retried": "true"},
        response=LIST,
    ),
    Case("gitlab_jobs", {"action": "get", "project": "grp/app", "job_id": 5}, "GET", JOB),
    Case(
        "gitlab_jobs",
        {"action": "get_log", "project": "grp/app", "job_id": 5},
        "GET",
        f"{JOB}/trace",
        response=StubResponse(content=b"$ make test\nok\n"),
    ),
    Case(
        "gitlab_jobs",
        {"action": "retry", "project": "grp/app", "job_id": 5},
        "POST",
        f"{JOB}/retry",
        response=StubResponse(status=201, json={"id": 6}),
    ),
    Case(
        "gitlab_jobs",
        {"action": "cancel", "project": "grp/app", "job_id": 5},
        "POST",
        f"{JOB}/cancel",
        response=StubResponse(status=201, json={"id": 5}),
    ),
    Case(
        "gitlab_jobs",
        {
            "action": "play",
            "project": "grp/app",
            "job_id": 5,
            "variables": [{"key": "TARGET", "value": "staging"}],
        },
        "POST",
        f"{JOB}/play",
        body={"job_variables_attributes": [{"key": "TARGET", "value": "staging"}]},
    ),
    Case(
        "gitlab_jobs",
        {"action": "list_artifacts", "project": "grp/app", "job_id": 5, "path": "coverage"},
        "GET",
        f"{JOB}/artifacts/tree",
        {**PAGE, "path": "coverage"},
        response=LIST,
    ),
    Case(
        "gitlab_jobs",
        {
            "action": "get_artifact_file",
            "project": "grp/app",
            "job_id": 5,
            "artifact_path": "coverage/index 1.html",
        },
        "GET",
        f"{JOB}/artifacts/coverage/index%201.html",
        response=StubResponse(content=b"<html></html>"),
    ),
    Case(
        "gitlab_ci_variables",
        {"action": "list", "project": "grp/app"},
        "GET",
        f"{P}/variables",
        PAGE,
        response=StubResponse(json=[VARIABLE]),
    ),
    Case(
        "gitlab_ci_variables",
        {"action": "get", "project": "grp/app", "key": "DEPLOY_TOKEN", "environment_scope": "prod"},
        "GET",
        f"{P}/variables/DEPLOY_TOKEN",
        {"filter[environment_scope]": "prod"},
        response=StubResponse(json=VARIABLE),
    ),
    Case(
        "gitlab_ci_variables",
        {
            "action": "create",
            "project": "grp/app",
            "key": "DEPLOY_TOKEN",
            "value": SECRET,
            "masked": True,
            "environment_scope": "prod",
        },
        "POST",
        f"{P}/variables",
        body={
            "key": "DEPLOY_TOKEN",
            "value": SECRET,
            "masked": True,
            "environment_scope": "prod",
        },
        response=StubResponse(status=201, json=VARIABLE),
    ),
    Case(
        "gitlab_ci_variables",
        {"action": "update", "project": "grp/app", "key": "DEPLOY_TOKEN", "value": "new-value!"},
        "PUT",
        f"{P}/variables/DEPLOY_TOKEN",
        body={"value": "new-value!"},
        response=StubResponse(json=VARIABLE),
    ),
    Case(
        "gitlab_ci_variables",
        {"action": "delete", "project": "grp/app", "key": "DEPLOY_TOKEN"},
        "DELETE",
        f"{P}/variables/DEPLOY_TOKEN",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "list", "project": "grp/app", "scope": "active"},
        "GET",
        f"{P}/pipeline_schedules",
        {**PAGE, "scope": "active"},
        response=LIST,
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "get", "project": "grp/app", "pipeline_schedule_id": 13},
        "GET",
        SCHEDULE,
        response=StubResponse(json=SCHEDULE_DETAILS),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "list_pipelines", "project": "grp/app", "pipeline_schedule_id": 13},
        "GET",
        f"{SCHEDULE}/pipelines",
        PAGE,
        response=LIST,
    ),
    Case(
        "gitlab_pipeline_schedules",
        {
            "action": "create",
            "project": "grp/app",
            "description": "Nightly",
            "ref": "main",
            "cron": "0 2 * * *",
            "cron_timezone": "UTC",
        },
        "POST",
        f"{P}/pipeline_schedules",
        body={"description": "Nightly", "ref": "main", "cron": "0 2 * * *", "cron_timezone": "UTC"},
        response=StubResponse(status=201, json={"id": 13}),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "update", "project": "grp/app", "pipeline_schedule_id": 13, "active": False},
        "PUT",
        SCHEDULE,
        body={"active": False},
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "take_ownership", "project": "grp/app", "pipeline_schedule_id": 13},
        "POST",
        f"{SCHEDULE}/take_ownership",
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "play", "project": "grp/app", "pipeline_schedule_id": 13},
        "POST",
        f"{SCHEDULE}/play",
        response=StubResponse(status=201, json={"message": "201 Created"}),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {"action": "delete", "project": "grp/app", "pipeline_schedule_id": 13},
        "DELETE",
        SCHEDULE,
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {
            "action": "create_variable",
            "project": "grp/app",
            "pipeline_schedule_id": 13,
            "key": "TARGET",
            "value": SECRET,
        },
        "POST",
        f"{SCHEDULE}/variables",
        body={"key": "TARGET", "value": SECRET},
        response=StubResponse(status=201, json=SCHEDULE_VARIABLE),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {
            "action": "update_variable",
            "project": "grp/app",
            "pipeline_schedule_id": 13,
            "key": "TARGET",
            "variable_type": "file",
        },
        "PUT",
        f"{SCHEDULE}/variables/TARGET",
        body={"variable_type": "file"},
        response=StubResponse(json=SCHEDULE_VARIABLE),
    ),
    Case(
        "gitlab_pipeline_schedules",
        {
            "action": "delete_variable",
            "project": "grp/app",
            "pipeline_schedule_id": 13,
            "key": "TARGET",
        },
        "DELETE",
        f"{SCHEDULE}/variables/TARGET",
        response=StubResponse(status=202, json=SCHEDULE_VARIABLE),
    ),
    Case(
        "gitlab_runners",
        {"action": "list", "status": "online", "tag_list": ["docker", "linux"]},
        "GET",
        "/runners",
        {**PAGE, "status": "online", "tag_list": "docker,linux"},
        response=LIST,
    ),
    Case(
        "gitlab_runners",
        {"action": "list", "project": "grp/app", "type": "instance_type"},
        "GET",
        f"{P}/runners",
        {**PAGE, "type": "instance_type"},
        response=LIST,
    ),
    Case(
        "gitlab_runners",
        {"action": "list", "group": "grp", "paused": True},
        "GET",
        "/groups/grp/runners",
        {**PAGE, "paused": "true"},
        response=LIST,
    ),
    Case(
        "gitlab_runners",
        {"action": "get", "runner_id": 6, "include_projects": False},
        "GET",
        "/runners/6",
        {"include_projects": "false"},
    ),
    Case(
        "gitlab_runners",
        {"action": "update", "runner_id": 6, "paused": True, "tag_list": ["docker"]},
        "PUT",
        "/runners/6",
        body={"paused": True, "tag_list": ["docker"]},
    ),
    Case(
        "gitlab_runners",
        {"action": "list_jobs", "runner_id": 6, "job_status": "running", "sort": "asc"},
        "GET",
        "/runners/6/jobs",
        {**PAGE, "status": "running", "sort": "asc"},
        response=LIST,
    ),
    Case(
        "gitlab_runners",
        {"action": "assign", "project": "grp/app", "runner_id": 6},
        "POST",
        f"{P}/runners",
        body={"runner_id": 6},
        response=StubResponse(status=201, json={"id": 6}),
    ),
    Case(
        "gitlab_runners",
        {"action": "unassign", "project": "grp/app", "runner_id": 6},
        "DELETE",
        f"{P}/runners/6",
        response=StubResponse(status=204),
    ),
    Case(
        "gitlab_runners",
        {"action": "delete", "runner_id": 6, "confirm": True},
        "DELETE",
        "/runners/6",
        response=StubResponse(status=204),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


def numbered_log(count: int) -> bytes:
    return "\n".join(f"line {number}" for number in range(count)).encode()


async def log_of(stub: GitLabStub, **arguments: object) -> dict[str, object]:
    outcome = await call(
        stub, "gitlab_jobs", {"action": "get_log", "project": "grp/app", "job_id": 5, **arguments}
    )
    assert outcome.is_error is False, outcome.structured
    return outcome.structured


async def test_get_log_returns_the_tail_by_default() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/trace", StubResponse(content=numbered_log(600)))
    log = await log_of(stub)
    assert (log["total_lines"], log["first_line"], log["returned_lines"]) == (600, 100, 500)
    assert log["truncated"] is True
    assert str(log["log"]).startswith("line 100\n") and str(log["log"]).endswith("line 599")


async def test_get_log_pages_from_an_offset_or_returns_everything() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/trace", StubResponse(content=numbered_log(600)))
    window = await log_of(stub, offset=10, tail_lines=3)
    assert window["log"] == "line 10\nline 11\nline 12"
    everything = await log_of(stub, full=True)
    assert everything["returned_lines"] == 600 and everything["truncated"] is False


async def test_get_log_strips_colors_markers_and_progress_redraws() -> None:
    raw = (
        b"section_start:1690000000:step_script\r\x1b[0K\x1b[32;1m$ make test\x1b[0;m\n"
        b"Downloading 10%\rDownloading 100%\r\n"
        b"\x1b[31;1mFAILED\x1b[0m\nsection_end:1690000001:step_script\r\x1b[0K"
    )
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/trace", StubResponse(content=raw))
    log = await log_of(stub, full=True)
    assert log["log"] == "$ make test\nDownloading 100%\nFAILED\n"


async def test_an_oversized_log_says_what_to_do() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/trace", StubResponse(content=b"x" * 2000))
    outcome = await call(
        stub,
        "gitlab_jobs",
        {"action": "get_log", "project": "grp/app", "job_id": 5},
        Settings(gitlab_max_response_bytes=1000),
    )
    error = outcome.structured["error"]
    assert error["code"] == "payload_too_large"
    assert "GITLAB_MAX_RESPONSE_BYTES" in error["message"]


async def test_job_scopes_are_sent_as_a_gitlab_array() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{PIPE}/jobs", LIST)
    await call(
        stub,
        "gitlab_jobs",
        {"action": "list", "project": "grp/app", "pipeline_id": 77, "scope": ["failed", "manual"]},
    )
    assert stub.requests[-1].url.params.get_list("scope[]") == ["failed", "manual"]


async def test_binary_artifacts_come_back_as_base64() -> None:
    blob = b"\x89PNG\r\n\x1a\n\x00\xff"
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/artifacts/shot.png", StubResponse(content=blob))
    outcome = await call(
        stub,
        "gitlab_jobs",
        {
            "action": "get_artifact_file",
            "project": "grp/app",
            "job_id": 5,
            "artifact_path": "shot.png",
        },
    )
    assert outcome.structured["encoding"] == "base64"
    assert base64.b64decode(outcome.structured["content"]) == blob


async def test_an_oversized_artifact_file_is_refused() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{JOB}/artifacts/big.log", StubResponse(content=b"x" * 2000))
    outcome = await call(
        stub,
        "gitlab_jobs",
        {
            "action": "get_artifact_file",
            "project": "grp/app",
            "job_id": 5,
            "artifact_path": "big.log",
        },
        Settings(gitlab_mcp_max_file_bytes=1000),
    )
    error = outcome.structured["error"]
    assert error["code"] == "payload_too_large"
    assert "list_artifacts" in error["message"]


@pytest.mark.parametrize("path", ["../../../../user", "a/../../b", "./x", "a//b"])
async def test_artifact_paths_cannot_leave_the_artifacts_route(path: str) -> None:
    stub = GitLabStub()
    outcome = await call(
        stub,
        "gitlab_jobs",
        {"action": "get_artifact_file", "project": "grp/app", "job_id": 5, "artifact_path": path},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_older_gitlab_lists_the_artifact_archives_instead() -> None:
    stub = GitLabStub()  # no /artifacts/tree route: GitLab before 18.8 answers 404
    archives = [{"file_type": "archive", "size": 1024, "filename": "artifacts.zip"}]
    stub.add("GET", JOB, StubResponse(json={"id": 5, "artifacts": archives}))
    outcome = await call(
        stub, "gitlab_jobs", {"action": "list_artifacts", "project": "grp/app", "job_id": 5}
    )
    assert outcome.structured["items"] == archives
    assert "18.8" in outcome.structured["note"]


async def test_a_job_without_artifacts_says_so() -> None:
    stub = GitLabStub()
    stub.add("GET", JOB, StubResponse(json={"id": 5, "artifacts": []}))
    outcome = await call(
        stub, "gitlab_jobs", {"action": "list_artifacts", "project": "grp/app", "job_id": 5}
    )
    assert outcome.structured == {"items": [], "note": "This job has no artifacts."}


async def test_pipeline_delete_requires_confirmation() -> None:
    stub = GitLabStub()
    outcome = await call(
        stub, "gitlab_pipelines", {"action": "delete", "project": "grp/app", "pipeline_id": 77}
    )
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


@pytest.mark.parametrize(
    ("action", "method", "path", "extra"),
    [
        ("list", "GET", f"{P}/variables", {}),
        ("get", "GET", f"{P}/variables/DEPLOY_TOKEN", {"key": "DEPLOY_TOKEN"}),
        ("create", "POST", f"{P}/variables", {"key": "DEPLOY_TOKEN", "value": SECRET}),
        ("update", "PUT", f"{P}/variables/DEPLOY_TOKEN", {"key": "DEPLOY_TOKEN", "value": "x"}),
    ],
)
async def test_variable_values_are_never_returned_by_default(
    action: str, method: str, path: str, extra: dict[str, str]
) -> None:
    stub = GitLabStub()
    stub.add(method, path, StubResponse(json=[VARIABLE] if action == "list" else VARIABLE))
    outcome = await call(
        stub, "gitlab_ci_variables", {"action": action, "project": "grp/app", **extra}
    )
    assert outcome.is_error is False, outcome.structured
    assert SECRET not in str(outcome.structured)
    shown = outcome.structured["items"][0] if action == "list" else outcome.structured
    assert shown["value_hidden"] is True and shown["key"] == "DEPLOY_TOKEN"


async def test_a_value_is_revealed_only_on_request() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/variables/DEPLOY_TOKEN", StubResponse(json=VARIABLE))
    outcome = await call(
        stub,
        "gitlab_ci_variables",
        {"action": "get", "project": "grp/app", "key": "DEPLOY_TOKEN", "reveal_value": True},
    )
    assert outcome.structured["value"] == SECRET


async def test_updating_a_flag_carries_the_value_over_server_side() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/variables/DEPLOY_TOKEN", StubResponse(json=VARIABLE))
    stub.add("PUT", f"{P}/variables/DEPLOY_TOKEN", StubResponse(json=VARIABLE))
    outcome = await call(
        stub,
        "gitlab_ci_variables",
        {
            "action": "update",
            "project": "grp/app",
            "key": "DEPLOY_TOKEN",
            "protected": False,
            "environment_scope": "prod",
        },
    )
    put = stub.requests[-1]
    assert body_of(put) == {"protected": False, "value": SECRET}
    assert put.url.params["filter[environment_scope]"] == "prod"
    assert SECRET not in str(outcome.structured)


async def test_a_hidden_value_cannot_be_carried_over() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/variables/KEY", StubResponse(json={**VARIABLE, "value": None}))
    outcome = await call(
        stub,
        "gitlab_ci_variables",
        {"action": "update", "project": "grp/app", "key": "KEY", "masked": True},
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert [request.method for request in stub.requests] == ["GET"]


@pytest.mark.parametrize("key", ["BAD-KEY", "with space", ""])
async def test_variable_keys_are_validated(key: str) -> None:
    outcome = await call(
        GitLabStub(), "gitlab_ci_variables", {"action": "get", "project": "grp/app", "key": key}
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    ("action", "extra", "path"),
    [
        ("get_log", {}, f"{P}/jobs/5/trace"),
        (
            "get_artifact_file",
            {"artifact_path": "dist/app.js"},
            f"{P}/jobs/5/artifacts/dist/app.js",
        ),
    ],
)
async def test_downloads_follow_gitlabs_hand_off_without_the_pat(
    action: str, extra: dict[str, str], path: str
) -> None:
    stub = GitLabStub()
    storage = "https://objects.example.com/signed/blob?X-Signature=abc"
    stub.add("GET", path, StubResponse(status=302, headers={"location": storage}))
    stub.add("GET", "/signed/blob", StubResponse(content=b"line one\nline two\n"))
    outcome = await call(
        stub, "gitlab_jobs", {"action": action, "project": "grp/app", "job_id": 5, **extra}
    )
    assert outcome.is_error is False, outcome.structured
    assert "line two" in str(outcome.structured)
    to_gitlab, to_storage = stub.requests
    assert to_gitlab.headers["authorization"].startswith("Bearer ")
    assert to_storage.url.host == "objects.example.com"
    assert "authorization" not in to_storage.headers


@pytest.mark.parametrize(
    ("action", "method", "path", "extra"),
    [
        ("list", "GET", f"{P}/pipeline_schedules", {}),
        ("get", "GET", SCHEDULE, {"pipeline_schedule_id": 13}),
        (
            "create",
            "POST",
            f"{P}/pipeline_schedules",
            {"description": "Nightly", "ref": "main", "cron": "0 2 * * *"},
        ),
        ("update", "PUT", SCHEDULE, {"pipeline_schedule_id": 13, "cron": "0 3 * * *"}),
        ("take_ownership", "POST", f"{SCHEDULE}/take_ownership", {"pipeline_schedule_id": 13}),
    ],
)
async def test_schedule_variable_values_are_never_returned_by_default(
    action: str, method: str, path: str, extra: dict[str, object]
) -> None:
    stub = GitLabStub()
    body = [SCHEDULE_DETAILS] if action == "list" else SCHEDULE_DETAILS
    stub.add(method, path, StubResponse(json=body))
    arguments = {"action": action, "project": "grp/app", **extra}
    outcome = await call(stub, "gitlab_pipeline_schedules", arguments)
    assert outcome.is_error is False, outcome.structured
    assert SECRET not in str(outcome.structured)
    schedule = outcome.structured["items"][0] if action == "list" else outcome.structured
    assert schedule["variables"] == [
        {"key": "TARGET", "variable_type": "env_var", "value_hidden": True}
    ]


@pytest.mark.parametrize(
    ("action", "method", "path", "extra"),
    [
        ("create_variable", "POST", f"{SCHEDULE}/variables", {"value": SECRET}),
        ("update_variable", "PUT", f"{SCHEDULE}/variables/TARGET", {"value": "x"}),
        ("delete_variable", "DELETE", f"{SCHEDULE}/variables/TARGET", {}),
    ],
)
async def test_schedule_variable_writes_never_echo_the_value(
    action: str, method: str, path: str, extra: dict[str, object]
) -> None:
    stub = GitLabStub()
    stub.add(method, path, StubResponse(json=SCHEDULE_VARIABLE))
    arguments = {
        "action": action,
        "project": "grp/app",
        "pipeline_schedule_id": 13,
        "key": "TARGET",
        **extra,
    }
    outcome = await call(stub, "gitlab_pipeline_schedules", arguments)
    assert outcome.is_error is False, outcome.structured
    assert SECRET not in str(outcome.structured)


async def test_schedule_variable_values_are_revealed_only_on_request() -> None:
    stub = GitLabStub()
    stub.add("GET", SCHEDULE, StubResponse(json=SCHEDULE_DETAILS))
    arguments = {"action": "get", "project": "grp/app", "pipeline_schedule_id": 13}
    outcome = await call(stub, "gitlab_pipeline_schedules", {**arguments, "reveal_values": True})
    assert outcome.structured["variables"][0]["value"] == SECRET


async def test_a_schedule_without_variables_is_returned_as_is() -> None:
    # Reporters see a schedule without its variables.
    stub = GitLabStub()
    stub.add("GET", SCHEDULE, StubResponse(json={"id": 13, "cron": "0 2 * * *"}))
    arguments = {"action": "get", "project": "grp/app", "pipeline_schedule_id": 13}
    outcome = await call(stub, "gitlab_pipeline_schedules", arguments)
    assert outcome.structured == {"id": 13, "cron": "0 2 * * *"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "update", "pipeline_schedule_id": 13},
        {"action": "update_variable", "pipeline_schedule_id": 13, "key": "TARGET"},
        {"action": "create", "description": "Nightly", "ref": "main"},
    ],
)
async def test_schedule_writes_need_their_fields(arguments: dict[str, object]) -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_pipeline_schedules", {**arguments, "project": "grp/app"})
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert stub.requests == []


async def test_runner_delete_requires_confirmation() -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_runners", {"action": "delete", "runner_id": 6})
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "list", "project": "grp/app", "group": "grp"},
        {"action": "update", "runner_id": 6},
        {"action": "assign", "runner_id": 6},
    ],
)
async def test_runner_actions_check_their_arguments(arguments: dict[str, object]) -> None:
    stub = GitLabStub()
    outcome = await call(stub, "gitlab_runners", arguments)
    assert outcome.structured["error"]["code"] == "invalid_arguments"
    assert stub.requests == []


def test_no_runner_action_hands_back_a_token() -> None:
    # Registering a runner and resetting tokens answer with a secret token (PRD-05 section 5).
    from mcp_gitlab.toolsets.pipelines.runners import RUNNERS_TOOL

    assert {action.name for action in RUNNERS_TOOL.actions} == {
        "list",
        "get",
        "update",
        "list_jobs",
        "assign",
        "unassign",
        "delete",
    }
