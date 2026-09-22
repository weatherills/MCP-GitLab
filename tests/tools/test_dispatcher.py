import logging

import pytest

from mcp_gitlab.config import Settings
from mcp_gitlab.core.errors import UnknownToolError
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.tools.dispatcher import Dispatcher, _structured
from mcp_gitlab.tools.registry import ToolRegistry
from tests.fakes import ALL_FAKE_TOOLSETS, TOKEN, request_context
from tests.support import GitLabStub, RecordingSleep, StubResponse


def dispatcher(stub: GitLabStub) -> Dispatcher:
    settings = Settings()
    client = GitLabClient(settings, transport=stub.transport(), sleep=RecordingSleep())
    return Dispatcher(ToolRegistry(ALL_FAKE_TOOLSETS), client, settings)


async def test_list_returns_items_and_pagination() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/group%2Fapp/widgets",
        StubResponse(json=[{"name": "w1"}], headers={"x-next-page": "2"}),
    )
    outcome = await dispatcher(stub).call(
        "fake_widgets", {"action": "list", "project": "group/app", "per_page": 5}, request_context()
    )
    assert outcome.is_error is False
    assert outcome.structured["items"] == [{"name": "w1"}]
    assert outcome.structured["pagination"]["has_more"] is True
    assert stub.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert dict(stub.requests[0].url.params) == {"page": "1", "per_page": "5"}


async def test_missing_credentials_are_reported() -> None:
    outcome = await dispatcher(GitLabStub()).call(
        "fake_widgets", {"action": "list", "project": "1"}, request_context(token=None)
    )
    assert outcome.is_error is True
    assert outcome.structured["error"]["code"] == "authentication_required"


async def test_destructive_action_requires_confirm() -> None:
    stub = GitLabStub()
    outcome = await dispatcher(stub).call(
        "fake_widgets", {"action": "delete", "project": "1", "widget": "w"}, request_context()
    )
    assert outcome.structured["error"]["code"] == "confirmation_required"
    assert stub.requests == []


async def test_confirmed_destructive_action_runs() -> None:
    stub = GitLabStub()
    stub.add("DELETE", "/projects/1/widgets/w%2F1", StubResponse(status=204))
    outcome = await dispatcher(stub).call(
        "fake_widgets",
        {"action": "delete", "project": "1", "widget": "w/1", "confirm": True},
        request_context(),
    )
    assert outcome.structured == {"deleted": "w/1"}


async def test_invalid_arguments_explain_themselves_without_echoing_values() -> None:
    outcome = await dispatcher(GitLabStub()).call(
        "fake_widgets", {"action": "list", "project": "", "per_page": 500}, request_context()
    )
    error = outcome.structured["error"]
    assert error["code"] == "invalid_arguments"
    fields = {problem["field"] for problem in error["details"]["problems"]}
    assert fields == {"project", "per_page"}
    assert "500" not in str(error["details"]["problems"])
    assert "project" in error["details"]["accepted_parameters"]


async def test_unknown_arguments_are_rejected() -> None:
    outcome = await dispatcher(GitLabStub()).call(
        "fake_widgets",
        {"action": "get", "project": "1", "widget": "w", "colour": "red"},
        request_context(),
    )
    assert outcome.structured["error"]["code"] == "invalid_arguments"


async def test_gitlab_errors_become_tool_errors() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/projects/1/widgets/missing",
        StubResponse(status=404, json={"message": "404 Widget Not Found"}),
    )
    outcome = await dispatcher(stub).call(
        "fake_widgets", {"action": "get", "project": "1", "widget": "missing"}, request_context()
    )
    assert outcome.is_error is True
    assert outcome.structured["error"]["code"] == "gitlab_not_found"
    assert outcome.structured["error"]["details"]["gitlab_message"] == "404 Widget Not Found"


async def test_unexpected_exceptions_are_masked_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        outcome = await dispatcher(GitLabStub()).call(
            "fake_widgets", {"action": "explode"}, request_context()
        )
    error = outcome.structured["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == "req-test"
    assert "internal detail" not in str(outcome.structured)
    assert any(record.exc_info for record in caplog.records)


async def test_unknown_tool_is_raised_for_the_transport_to_map() -> None:
    with pytest.raises(UnknownToolError):
        await dispatcher(GitLabStub()).call("nope", {"action": "list"}, request_context())


async def test_tool_call_log_records_argument_names_not_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects/1/widgets", StubResponse(status=201, json={"name": "secret-name"}))
    with caplog.at_level(logging.INFO, logger="mcp_gitlab.tools.dispatcher"):
        await dispatcher(stub).call(
            "fake_widgets",
            {"action": "create", "project": "1", "widget": "secret-name"},
            request_context(),
        )
    [record] = [r for r in caplog.records if r.getMessage() == "tool_call"]
    fields = record.fields  # type: ignore[attr-defined]
    assert fields["outcome"] == "ok"
    assert fields["arguments"] == ["project", "widget"]
    assert "secret-name" not in repr(fields)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, {"success": True}),
        (["a"], {"items": ["a"]}),
        (3, {"result": 3}),
        ({"k": 1}, {"k": 1}),
    ],
)
def test_results_are_normalised_to_objects(result: object, expected: dict[str, object]) -> None:
    assert _structured(result) == expected
