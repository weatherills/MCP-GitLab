"""Retry decisions for outbound GitLab calls (PRD-00 section 10).

429 is retried for every method because GitLab rejected the request before
processing it. 5xx responses and failures after a request was sent are retried
only for idempotent methods: a POST that failed server-side may already have
been applied, and resending it could, for example, create a duplicate commit.
"""

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    max_network_retries: int = 1
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: Callable[[], float] = field(default=random.random, repr=False, compare=False)

    def delay_after_status(
        self, method: str, status: int, headers: Mapping[str, str], retries_so_far: int
    ) -> float | None:
        if retries_so_far >= self.max_retries:
            return None
        if status != 429 and not (status >= 500 and method.upper() in IDEMPOTENT_METHODS):
            return None
        hinted = retry_after_seconds(headers)
        if hinted is None:
            return self.backoff(retries_so_far + 1)
        # Waiting past max_delay just to be rate limited again helps nobody; surface it instead.
        return hinted if hinted <= self.max_delay else None

    def delay_after_transport_error(
        self, method: str, error: httpx.TransportError, retries_so_far: int
    ) -> float | None:
        if retries_so_far >= self.max_network_retries:
            return None
        if not isinstance(error, _NEVER_SENT) and method.upper() not in IDEMPOTENT_METHODS:
            return None
        return self.backoff(retries_so_far + 1)

    def backoff(self, retry_number: int) -> float:
        """Exponential backoff with full jitter."""
        return self.jitter() * min(self.max_delay, self.base_delay * 2.0 ** (retry_number - 1))


def retry_after_seconds(
    headers: Mapping[str, str], *, now: Callable[[], datetime] | None = None
) -> float | None:
    current = (now or _utcnow)()
    value = (headers.get("retry-after") or "").strip()
    if value.isdigit():
        return float(value)
    if value:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - current).total_seconds())
    reset = (headers.get("ratelimit-reset") or "").strip()
    if reset.isdigit():
        return max(0.0, int(reset) - current.timestamp())
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
