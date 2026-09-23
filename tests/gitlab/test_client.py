import logging
import ssl
from pathlib import Path

import httpx
import pytest

from mcp_gitlab.config import Settings
from mcp_gitlab.core.errors import (
    GitLabBadRequestError,
    GitLabError,
    GitLabNotFoundError,
    GitLabRateLimitedError,
    GitLabServerError,
    GitLabUnavailableError,
    GitLabUnprocessableError,
    PayloadTooLargeError,
)
from mcp_gitlab.gitlab.client import GitLabClient, _tls_verification
from mcp_gitlab.gitlab.paths import project_path
from mcp_gitlab.gitlab.retry import RetryPolicy
from tests.support import ChunkedStream, GitLabStub, RecordingSleep, StubResponse

TOKEN = "glpat-abcdefghijklmnopqrstu"
TEST_CA = Path(__file__).parent.parent / "fixtures" / "test-ca.pem"


def make_client(
    stub: GitLabStub, sleep: RecordingSleep | None = None, **settings: object
) -> GitLabClient:
    return GitLabClient(
        Settings(gitlab_base_url="https://gitlab.example.com/api/v4", **settings),  # type: ignore[arg-type]
        transport=stub.transport(),
        retry=RetryPolicy(max_retries=3, jitter=lambda: 1.0),
        sleep=sleep or RecordingSleep(),
    )


async def test_forwards_token_and_identifies_itself() -> None:
    stub = GitLabStub()
    stub.add("GET", "/user", StubResponse(json={"id": 1}))
    assert await make_client(stub).session(TOKEN).get("/user") == {"id": 1}
    request = stub.requests[0]
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["user-agent"].startswith("mcp-gitlab/")
    assert request.headers["accept"] == "application/json"


async def test_preserves_encoded_path_segments() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects/group%2Fproject", StubResponse(json={"id": 7}))
    assert await make_client(stub).session(TOKEN).get(project_path("group/project")) == {"id": 7}
    assert stub.paths() == ["/api/v4/projects/group%2Fproject"]


async def test_drops_none_params() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects", StubResponse(json=[]))
    await (
        make_client(stub)
        .session(TOKEN)
        .get("/projects", params={"search": "api", "owned": None, "archived": False})
    )
    assert dict(stub.requests[0].url.params) == {"search": "api", "archived": "false"}


async def test_empty_body_is_none() -> None:
    stub = GitLabStub()
    stub.add("DELETE", "/projects/1", StubResponse(status=204))
    assert await make_client(stub).session(TOKEN).delete("/projects/1") is None


async def test_get_page_returns_items_and_pagination() -> None:
    stub = GitLabStub()
    headers = {
        "x-page": "2",
        "x-per-page": "20",
        "x-next-page": "3",
        "x-prev-page": "1",
        "x-total": "45",
    }
    stub.add("GET", "/projects", StubResponse(json=[{"id": 1}], headers=headers))
    page = await make_client(stub).session(TOKEN).get_page("/projects", params={"page": 2})
    assert page.to_dict() == {
        "items": [{"id": 1}],
        "pagination": {
            "page": 2,
            "per_page": 20,
            "next_page": 3,
            "prev_page": 1,
            "total": 45,
            "total_pages": None,
            "has_more": True,
        },
    }


async def test_get_page_rejects_non_list() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects", StubResponse(json={"not": "a list"}))
    with pytest.raises(GitLabError, match="Expected a list"):
        await make_client(stub).session(TOKEN).get_page("/projects")


async def test_not_found_passes_gitlab_message_through() -> None:
    stub = GitLabStub()
    stub.add(
        "GET", "/projects/9", StubResponse(status=404, json={"message": "404 Project Not Found"})
    )
    with pytest.raises(GitLabNotFoundError) as excinfo:
        await make_client(stub).session(TOKEN).get("/projects/9")
    payload = excinfo.value.to_payload()
    assert payload["code"] == "gitlab_not_found"
    assert payload["status"] == 404
    assert payload["details"]["gitlab_message"] == "404 Project Not Found"
    assert "404 Project Not Found" in payload["message"]


async def test_structured_validation_messages_are_preserved() -> None:
    stub = GitLabStub()
    body = {"message": {"name": ["has already been taken"]}}
    stub.add("POST", "/projects", StubResponse(status=422, json=body))
    with pytest.raises(GitLabUnprocessableError) as excinfo:
        await make_client(stub).session(TOKEN).post("/projects", json_body={"name": "x"})
    assert excinfo.value.details["gitlab_message"] == {"name": ["has already been taken"]}


async def test_non_json_error_body_is_passed_as_text() -> None:
    stub = GitLabStub()
    stub.add("GET", "/broken", StubResponse(status=400, content=b"Bad things happened"))
    with pytest.raises(GitLabBadRequestError) as excinfo:
        await make_client(stub).session(TOKEN).get("/broken")
    assert excinfo.value.details["gitlab_message"] == "Bad things happened"


async def test_rate_limit_retries_after_hinted_delay() -> None:
    stub, sleep = GitLabStub(), RecordingSleep()
    stub.add(
        "POST",
        "/projects",
        StubResponse(status=429, headers={"retry-after": "2"}),
        StubResponse(status=201, json={"id": 3}),
    )
    assert await make_client(stub, sleep).session(TOKEN).post("/projects", json_body={}) == {
        "id": 3
    }
    assert sleep.delays == [2.0]
    assert len(stub.requests) == 2


async def test_long_rate_limit_is_surfaced_not_waited_out() -> None:
    stub, sleep = GitLabStub(), RecordingSleep()
    stub.add("GET", "/projects", StubResponse(status=429, headers={"retry-after": "3600"}))
    with pytest.raises(GitLabRateLimitedError) as excinfo:
        await make_client(stub, sleep).session(TOKEN).get("/projects")
    assert excinfo.value.retryable is True
    assert excinfo.value.details["retry_after_seconds"] == 3600.0
    assert sleep.delays == []


async def test_idempotent_server_errors_are_retried() -> None:
    stub, sleep = GitLabStub(), RecordingSleep()
    stub.add(
        "GET",
        "/projects",
        StubResponse(status=503),
        StubResponse(status=502),
        StubResponse(json=[]),
    )
    assert await make_client(stub, sleep).session(TOKEN).get("/projects") == []
    assert sleep.delays == [0.5, 1.0]


async def test_non_idempotent_server_errors_are_not_retried() -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects/1/repository/commits", StubResponse(status=502))
    with pytest.raises(GitLabServerError):
        await make_client(stub).session(TOKEN).post("/projects/1/repository/commits", json_body={})
    assert len(stub.requests) == 1


async def test_retries_stop_at_the_bound() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects", StubResponse(status=503))
    with pytest.raises(GitLabServerError):
        await make_client(stub).session(TOKEN).get("/projects")
    assert len(stub.requests) == 4


async def test_connect_failure_is_retried_once_even_for_post() -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects", httpx.ConnectError, StubResponse(status=201, json={"id": 5}))
    assert await make_client(stub).session(TOKEN).post("/projects", json_body={}) == {"id": 5}
    assert len(stub.requests) == 2


async def test_read_timeout_on_post_is_not_retried() -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects", httpx.ReadTimeout)
    with pytest.raises(GitLabUnavailableError):
        await make_client(stub).session(TOKEN).post("/projects", json_body={})
    assert len(stub.requests) == 1


async def test_persistent_network_failure_gets_one_retry() -> None:
    stub = GitLabStub()
    stub.add("GET", "/projects", httpx.ReadTimeout)
    with pytest.raises(GitLabUnavailableError):
        await make_client(stub).session(TOKEN).get("/projects")
    assert len(stub.requests) == 2


async def test_declared_oversized_response_is_rejected() -> None:
    stub = GitLabStub()
    stub.add("GET", "/big", StubResponse(content=b"x" * 64))
    with pytest.raises(PayloadTooLargeError):
        await make_client(stub, gitlab_max_response_bytes=32).session(TOKEN).get_bytes("/big")


async def test_streamed_oversized_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ChunkedStream([b"x" * 20, b"x" * 20]))

    client = GitLabClient(
        Settings(gitlab_max_response_bytes=32),
        transport=httpx.MockTransport(handler),
        sleep=RecordingSleep(),
    )
    with pytest.raises(PayloadTooLargeError):
        await client.session(TOKEN).get_bytes("/big")


async def test_per_call_limit_overrides_default() -> None:
    stub = GitLabStub()
    stub.add("GET", "/file", StubResponse(content=b"x" * 64))
    session = make_client(stub).session(TOKEN)
    with pytest.raises(PayloadTooLargeError):
        await session.get_bytes("/file", max_bytes=16)
    assert await session.get_bytes("/file") == b"x" * 64


async def test_token_never_reaches_logs(caplog: pytest.LogCaptureFixture) -> None:
    stub = GitLabStub()
    stub.add("GET", "/user", StubResponse(json={}))
    with caplog.at_level(logging.INFO):
        await make_client(stub).session(TOKEN).get("/user")
    assert caplog.records, "expected a gitlab_request log entry"
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in repr(getattr(record, "fields", {}))


async def test_each_gitlab_call_is_logged_with_its_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = GitLabStub()
    stub.add("GET", "/user", StubResponse(json={}, headers={"x-request-id": "gl-req-7"}))
    with caplog.at_level(logging.INFO, logger="mcp_gitlab.gitlab.client"):
        await make_client(stub).session(TOKEN).get("/user")
    [record] = [r for r in caplog.records if r.getMessage() == "gitlab_request"]
    fields = dict(record.fields)  # type: ignore[attr-defined]
    duration = fields.pop("duration_ms")
    assert isinstance(duration, float) and duration >= 0
    assert fields == {
        "method": "GET",
        "path": "/user",
        "attempt": 1,
        "status": 200,
        "gitlab_request_id": "gl-req-7",
    }


def test_session_hides_token_from_repr() -> None:
    assert TOKEN not in repr(make_client(GitLabStub()).session(TOKEN))


def test_tls_verification_defaults_to_system_trust() -> None:
    assert isinstance(_tls_verification(Settings()), ssl.SSLContext)


def test_tls_verification_can_be_skipped_for_self_hosted() -> None:
    settings = Settings(
        gitlab_base_url="https://gitlab.internal/api/v4", gitlab_skip_tls_verify=True
    )
    assert _tls_verification(settings) is False


def test_a_custom_ca_bundle_replaces_the_system_trust() -> None:
    settings = Settings(
        gitlab_base_url="https://gitlab.internal/api/v4", gitlab_ca_bundle=str(TEST_CA)
    )
    context = _tls_verification(settings)
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    trusted = [dict(pair for rdn in ca["subject"] for pair in rdn) for ca in context.get_ca_certs()]
    assert trusted == [{"commonName": "mcp-gitlab test CA"}]


async def test_cookies_never_carry_over_between_requests() -> None:
    stub = GitLabStub()
    stub.add(
        "GET",
        "/user",
        StubResponse(json={"id": 1}, headers={"set-cookie": "_gitlab_session=alice; Path=/"}),
    )
    client = make_client(stub)
    await client.session("glpat-alice-abcdefghijkl").get("/user")
    await client.session("glpat-bob-abcdefghijklmn").get("/user")
    await client.session("glpat-alice-abcdefghijkl").get("/user")
    assert [request.headers.get("cookie") for request in stub.requests] == [None, None, None]
    assert [request.headers["authorization"] for request in stub.requests] == [
        "Bearer glpat-alice-abcdefghijkl",
        "Bearer glpat-bob-abcdefghijklmn",
        "Bearer glpat-alice-abcdefghijkl",
    ]


class RedirectingGitLab(httpx.MockTransport):
    """GitLab that hands a download off to a CDN, recording who sent which Authorization."""

    def __init__(self, location: str, *, hops: int = 1) -> None:
        self.seen: list[tuple[str, str | None]] = []
        self._location = location
        self._hops = hops
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((str(request.url), request.headers.get("authorization")))
        if len(self.seen) <= self._hops:
            return httpx.Response(302, headers={"location": self._location})
        return httpx.Response(200, content=b"artifact bytes")


def redirect_client(transport: httpx.MockTransport) -> GitLabClient:
    return GitLabClient(
        Settings(gitlab_base_url="https://gitlab.example.com/api/v4"),
        transport=transport,
        sleep=RecordingSleep(),
    )


async def test_a_download_redirect_to_another_host_never_carries_the_pat() -> None:
    cdn = "https://cdn.example.net/artifacts/file.txt?X-Signature=abc"
    transport = RedirectingGitLab(cdn)
    session = redirect_client(transport).session(TOKEN)
    data = await session.get_bytes("/projects/1/jobs/5/artifacts/file.txt", follow_redirects=True)
    assert data == b"artifact bytes"
    assert transport.seen == [
        (
            "https://gitlab.example.com/api/v4/projects/1/jobs/5/artifacts/file.txt",
            f"Bearer {TOKEN}",
        ),
        (cdn, None),
    ]


async def test_a_download_redirect_within_gitlab_keeps_the_pat() -> None:
    transport = RedirectingGitLab("/api/v4/projects/1/jobs/5/trace?archived=1")
    session = redirect_client(transport).session(TOKEN)
    await session.get_bytes("/projects/1/jobs/5/trace", follow_redirects=True)
    assert [authorization for _, authorization in transport.seen] == [f"Bearer {TOKEN}"] * 2


async def test_a_redirect_to_another_port_on_the_same_host_drops_the_pat() -> None:
    transport = RedirectingGitLab("https://gitlab.example.com:8443/storage/file")
    session = redirect_client(transport).session(TOKEN)
    await session.get_bytes("/projects/1/jobs/5/trace", follow_redirects=True)
    assert transport.seen[1][1] is None


async def test_redirects_are_not_followed_unless_asked() -> None:
    transport = RedirectingGitLab("https://cdn.example.net/file")
    session = redirect_client(transport).session(TOKEN)
    with pytest.raises(GitLabError, match="not followed") as caught:
        await session.get("/projects/1")
    assert caught.value.status == 302
    assert len(transport.seen) == 1


async def test_redirect_chains_are_bounded() -> None:
    transport = RedirectingGitLab("https://cdn.example.net/loop", hops=10)
    session = redirect_client(transport).session(TOKEN)
    with pytest.raises(GitLabError, match="too many times"):
        await session.get_bytes("/projects/1/jobs/5/trace", follow_redirects=True)
    assert len(transport.seen) == 4  # the request plus three hops


async def test_not_modified_is_still_a_success() -> None:
    stub = GitLabStub()
    stub.add("POST", "/projects/1/star", StubResponse(status=304))
    assert await make_client(stub).session(TOKEN).post("/projects/1/star") is None
