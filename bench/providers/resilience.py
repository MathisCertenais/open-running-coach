"""Retry policy, backoff and per-model pacing for the HTTP adapter.

The capture loop stays transport-agnostic: nothing in ``runner.py`` imports
this module. The adapter owns the decision to call a provider again, because it
is the layer that can classify a 429 from a 401 and read ``Retry-After`` off
the exception's cause.

Two independent clocks matter here:

- the **timeout budget** is the request's ``timeout_s``. Every attempt gets the
  remaining budget, and a plan that starts a second attempt after 179 of 180
  seconds has one second, not a fresh three minutes;
- the **pacing interval** is a minimum spacing between request starts to the
  same origin/model, derived from a published rate limit. It applies to retries
  too: a retry is still a request against the same budget.

Both are injected so tests never sleep on a real clock.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping
from urllib.error import HTTPError

from .. import config
from .base import ModelSpec


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts, and how long to wait between them."""

    max_attempts: int = config.RETRY_MAX_ATTEMPTS
    base_delay_s: float = config.RETRY_BASE_DELAY_S
    max_delay_s: float = config.RETRY_MAX_DELAY_S

    def backoff(self, attempt: int, rng: Callable[[float, float], float]) -> float:
        """Full-jitter exponential backoff after ``attempt`` (1-based).

        The ceiling doubles per attempt and is capped; the delay is drawn from
        ``[0, ceiling]`` so concurrent clients do not retry in lockstep.
        """
        ceiling = min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
        return float(rng(0.0, ceiling)) if ceiling > 0 else 0.0


def parse_retry_after(
    value: str | None, *, now: datetime | None = None
) -> float | None:
    """Parse ``Retry-After`` as delta-seconds or an HTTP-date into seconds.

    Returns ``None`` when the header is absent or malformed, so the caller
    falls back to jittered backoff rather than guessing. A date in the past
    becomes ``0.0``.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - reference).total_seconds())


class Pacer:
    """The next allowed start time for one origin/model key."""

    def __init__(
        self,
        interval_s: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.interval_s = max(0.0, float(interval_s))
        self._clock = clock
        self._sleep = sleep
        self._next_at: float | None = None

    def wait(self) -> float:
        """Sleep until this key may start again; return the seconds spent."""
        if self.interval_s <= 0:
            return 0.0
        now = self._clock()
        if self._next_at is None:
            self._next_at = now
        delay = self._next_at - now
        if delay > 0:
            self._sleep(delay)
            now = self._clock()
        self._next_at = now + self.interval_s
        return max(0.0, delay)


class PacerRegistry:
    """One pacer per origin/model, so two origins never block each other."""

    def __init__(
        self, *, clock: Callable[[], float], sleep: Callable[[float], None]
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._pacers: dict[str, Pacer] = {}

    def wait(self, key: str, interval_s: float) -> float:
        """Wait for ``key`` at ``interval_s`` spacing and return the wait."""
        pacer = self._pacers.get(key)
        if pacer is None or pacer.interval_s != max(0.0, float(interval_s)):
            pacer = Pacer(interval_s, clock=self._clock, sleep=self._sleep)
            self._pacers[key] = pacer
        return pacer.wait()


def pacing_key(spec: ModelSpec) -> str:
    """The pacing identity: same origin and model share one rate limit."""
    return f"{spec.origin}|{spec.model}"


def pacing_interval(spec: ModelSpec) -> float:
    """Configured interval for this roster entry, or the unpaced default."""
    for key in (spec.key, spec.registry_id or ""):
        if key and key in config.PACING_INTERVALS:
            return float(config.PACING_INTERVALS[key])
    return float(config.PACING_DEFAULT_INTERVAL_S)


@dataclass(frozen=True)
class AttemptOutcome:
    """What the retry loop produced, including why it stopped.

    ``usage`` holds any token counts a failed attempt reported before it
    failed, so a retried call's cost is not silently dropped.
    """

    value: object | None
    error: Exception | None
    attempts: int
    reasons: tuple[str, ...]
    waits: Mapping[str, float] = field(default_factory=dict)
    budget_exhausted: bool = False
    usage: tuple[Mapping[str, object], ...] = ()

    @property
    def retried(self) -> bool:
        """True when at least one attempt failed and another followed."""
        return bool(self.reasons)

    @property
    def wait_s(self) -> float:
        """Total seconds spent sleeping between attempts."""
        return round(sum(self.waits.values()), 6)

    def wait_for(self, reason: str) -> float:
        """Seconds spent waiting because of one retry reason (e.g. ``"429"``)."""
        return round(float(self.waits.get(reason, 0.0)), 6)


def call_with_retry(
    operation: Callable[[float], object],
    *,
    policy: RetryPolicy,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    retryable: Callable[[Exception], str | None],
    retry_after: Callable[[Exception], float | None],
    budget_s: float,
    before_attempt: Callable[[], None] | None = None,
    rng: Callable[[float, float], float] = random.uniform,
) -> AttemptOutcome:
    """Call ``operation(remaining_budget_s)`` until it succeeds or must stop.

    ``retryable`` returns a short reason label (``"429"``, ``"503"``,
    ``"timeout"``) or ``None`` to give up. ``retry_after`` reads the provider's
    own delay when it sent one; a server delay is honoured as-is, jitter is
    only used in its absence. ``before_attempt`` runs inside the budget (the
    rate limiter uses it) and the budget is checked *after* it: a wait that
    would overrun exhausts the record instead of starting a request the budget
    cannot cover. The timeout budget never resets.
    """
    deadline = clock() + max(0.0, float(budget_s))
    waits: dict[str, float] = {}
    reasons: list[str] = []
    usages: list[Mapping[str, object]] = []
    last_error: Exception | None = None
    attempt = 0
    while True:
        if attempt and deadline - clock() <= 0:
            return AttemptOutcome(
                None,
                last_error,
                attempt,
                tuple(reasons),
                dict(waits),
                True,
                tuple(usages),
            )
        attempt += 1
        if before_attempt is not None:
            before_attempt()
            if deadline - clock() <= 0:
                return AttemptOutcome(
                    None,
                    TimeoutError(
                        f"timeout budget of {budget_s:g}s exhausted while pacing"
                    ),
                    attempt,
                    tuple(reasons),
                    dict(waits),
                    True,
                    tuple(usages),
                )
        try:
            value = operation(max(deadline - clock(), 0.0))
            return AttemptOutcome(
                value,
                None,
                attempt,
                tuple(reasons),
                dict(waits),
                False,
                tuple(usages),
            )
        except Exception as exc:  # converted to AttemptOutcome: data, not a crash
            last_error = exc
            usage = getattr(exc, "usage", None)
            if isinstance(usage, Mapping):
                usages.append(dict(usage))
            reason = retryable(exc)
            if reason is None or attempt >= policy.max_attempts:
                return AttemptOutcome(
                    None,
                    exc,
                    attempt,
                    tuple(reasons),
                    dict(waits),
                    False,
                    tuple(usages),
                )
            server_delay = retry_after(exc)
            delay = (
                server_delay
                if server_delay is not None
                else policy.backoff(attempt, rng)
            )
            reasons.append(reason)
            if clock() + delay >= deadline:
                return AttemptOutcome(
                    None,
                    exc,
                    attempt,
                    tuple(reasons),
                    dict(waits),
                    True,
                    tuple(usages),
                )
            sleep(delay)
            waits[reason] = waits.get(reason, 0.0) + delay


_HTTP_CODE = re.compile(r"HTTP (\d{3})")
# 429 is the provider's own rate limit; 5xx is the server's problem. 408 and
# 425 are retried as timeouts, never as generic 4xx.
_RETRYABLE_HTTP = frozenset({408, 425, 429})


def http_status(exc: Exception) -> int | None:
    """The HTTP status behind an ``LLMError``, from its cause or its message."""
    cause = exc.__cause__
    code = getattr(cause, "code", None)
    if isinstance(code, int):
        return code
    match = _HTTP_CODE.search(str(exc))
    return int(match.group(1)) if match else None


def retry_reason(exc: Exception) -> str | None:
    """The label recorded when this failure is worth another attempt."""
    code = http_status(exc)
    if code is not None:
        if code == 429:
            return "429"
        if 500 <= code < 600 or code in _RETRYABLE_HTTP:
            return str(code)
        return None
    lowered = str(exc).lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    return None


def retry_after(exc: Exception) -> float | None:
    """Read ``Retry-After`` from the HTTP error that raised the LLM error.

    ``coach_llm._send`` re-raises ``LLMError`` ``from`` the ``HTTPError``, so
    the response headers are still reachable without re-implementing the
    transport.
    """
    cause = exc.__cause__
    if not isinstance(cause, HTTPError):
        return None
    value = cause.headers.get("Retry-After") if cause.headers else None
    return parse_retry_after(value)
