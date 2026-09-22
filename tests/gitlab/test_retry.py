from datetime import datetime, timezone

import httpx
import pytest

from mcp_gitlab.gitlab.retry import RetryPolicy, retry_after_seconds

POLICY = RetryPolicy(max_retries=3, jitter=lambda: 1.0)
NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_429_is_retried_for_every_method(method: str) -> None:
    assert POLICY.delay_after_status(method, 429, {}, 0) is not None


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "DELETE"])
def test_5xx_is_retried_for_idempotent_methods(method: str) -> None:
    assert POLICY.delay_after_status(method, 503, {}, 0) is not None


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_5xx_is_not_retried_for_non_idempotent_methods(method: str) -> None:
    assert POLICY.delay_after_status(method, 502, {}, 0) is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_errors_are_never_retried(status: int) -> None:
    assert POLICY.delay_after_status("GET", status, {}, 0) is None


def test_retries_are_bounded() -> None:
    assert POLICY.delay_after_status("GET", 503, {}, 2) is not None
    assert POLICY.delay_after_status("GET", 503, {}, 3) is None


def test_backoff_is_exponential_and_capped() -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=3.0, jitter=lambda: 1.0)
    assert [policy.backoff(n) for n in (1, 2, 3, 4, 5)] == [0.5, 1.0, 2.0, 3.0, 3.0]


def test_backoff_applies_full_jitter() -> None:
    assert RetryPolicy(base_delay=4.0, jitter=lambda: 0.25).backoff(1) == 1.0


def test_retry_after_header_is_honoured() -> None:
    assert POLICY.delay_after_status("GET", 429, {"retry-after": "7"}, 0) == 7.0


def test_retry_after_beyond_max_delay_is_not_waited_out() -> None:
    assert POLICY.delay_after_status("GET", 429, {"retry-after": "3600"}, 0) is None


def test_connect_errors_are_retried_once_for_any_method() -> None:
    error = httpx.ConnectError("refused")
    assert POLICY.delay_after_transport_error("POST", error, 0) is not None
    assert POLICY.delay_after_transport_error("POST", error, 1) is None


def test_read_failures_are_retried_only_for_idempotent_methods() -> None:
    error = httpx.ReadTimeout("slow")
    assert POLICY.delay_after_transport_error("GET", error, 0) is not None
    assert POLICY.delay_after_transport_error("POST", error, 0) is None


def test_retry_after_seconds_parses_integer() -> None:
    assert retry_after_seconds({"retry-after": "12"}) == 12.0


def test_retry_after_seconds_parses_http_date() -> None:
    headers = {"retry-after": "Tue, 22 Sep 2026 12:00:30 GMT"}
    assert retry_after_seconds(headers, now=lambda: NOW) == 30.0


def test_retry_after_seconds_falls_back_to_ratelimit_reset() -> None:
    headers = {"ratelimit-reset": str(int(NOW.timestamp()) + 45)}
    assert retry_after_seconds(headers, now=lambda: NOW) == 45.0


def test_retry_after_seconds_ignores_garbage() -> None:
    assert retry_after_seconds({"retry-after": "soon"}) is None
