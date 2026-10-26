"""Retry policy, pacing and the record's attempt accounting.

No test here sleeps for real or touches the network: the adapter takes a clock,
a sleep function and an interval map, and ``coach_llm.run_chat`` is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError

from app import coach_llm
from bench import config, records
from bench.providers.base import (
    AvailabilityStatus,
    ErrorKind,
    Pricing,
    Request,
    Status,
)
from bench.providers.openai_http import OpenAIHTTPProvider, retry_reason
from bench.providers.resilience import (
    Pacer,
    RetryPolicy,
    parse_retry_after,
)
from tests.bench_helpers import NOW, make_completion, make_fixture, make_plan, make_spec

TRACE = coach_llm.ChatTrace(
    text="A grounded answer.",
    tool_calls=(),
    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    rounds=1,
    tools_offered=0,
    tools_dropped=False,
    finish_reason="stop",
    context_chars=500,
    context_truncated=False,
)


class FakeClock:
    """Monotonic clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def http_error(code: int, headers: dict[str, str] | None = None) -> coach_llm.LLMError:
    """An LLMError shaped the way ``coach_llm._send`` raises one."""
    cause = HTTPError(
        "https://example.test/v1/chat/completions",
        code,
        "error",
        Message() if headers is None else _headers(headers),
        None,
    )
    error = coach_llm.LLMError(f"M returned HTTP {code}: provider said no")
    error.__cause__ = cause
    return error


def _headers(values: dict[str, str]) -> Message:
    message = Message()
    for key, value in values.items():
        message[key] = value
    return message


def provider(
    clock: FakeClock,
    *,
    max_attempts: int = 3,
    intervals: dict[str, float] | None = None,
    jitter: str = "max",
) -> OpenAIHTTPProvider:
    rng = (lambda low, high: high) if jitter == "max" else (lambda low, high: 0.0)
    return OpenAIHTTPProvider(
        policy=RetryPolicy(
            max_attempts=max_attempts,
            base_delay_s=config.RETRY_BASE_DELAY_S,
            max_delay_s=config.RETRY_MAX_DELAY_S,
        ),
        intervals={} if intervals is None else intervals,
        clock=clock,
        sleep=clock.sleep,
        rng=rng,
    )


def request(
    timeout_s: float = 60.0, *, key: str = "albert-qwen", origin: str = "albert"
):
    spec = make_spec(
        key,
        adapter="openai_http",
        origin=origin,
        model="provider-model",
        registry_id="ollama-local",
    )
    return Request(
        model=spec,
        snapshot={"load": {"last_7d": 100}},
        user_message="What should I do this week?",
        tool_context={"activities": []},
        timeout_s=timeout_s,
    )


def test_429_then_success_is_one_retry(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(429)
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    completion = provider(clock).complete(request())

    assert completion.status == Status.OK
    assert completion.text == "A grounded answer."
    assert completion.diagnostics["attempts"] == 2
    assert completion.diagnostics["retried"] is True
    assert completion.diagnostics["retry_reasons"] == ["429"]
    assert clock.sleeps == [config.RETRY_BASE_DELAY_S]


def test_retry_after_is_honoured(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http_error(429, {"Retry-After": "2"})
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    # Jitter is forced to zero: the only reason to sleep 2 s is the header.
    completion = provider(clock, jitter="min").complete(request())

    assert completion.status == Status.OK
    assert clock.sleeps == [2.0]


def test_retry_after_accepts_an_http_date():
    now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

    assert parse_retry_after("2", now=now) == 2.0
    assert parse_retry_after("Mon, 26 Oct 2026 12:00:02 GMT", now=now) == 2.0
    assert parse_retry_after("Mon, 26 Oct 2026 11:59:00 GMT", now=now) == 0.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None


def test_401_is_not_retried(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        raise http_error(401)

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    completion = provider(clock).complete(request())

    assert calls["n"] == 1
    assert completion.status == Status.ERROR
    assert completion.error_kind == ErrorKind.AUTH
    assert completion.diagnostics["attempts"] == 1
    assert completion.diagnostics["retried"] is False
    assert clock.sleeps == []


def test_persistent_429_stops_at_the_attempt_cap(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        raise http_error(429, {"Retry-After": "1"})

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    completion = provider(clock, max_attempts=3).complete(request(timeout_s=600))

    assert calls["n"] == 3
    assert completion.status == Status.ERROR
    assert completion.error_kind == ErrorKind.RATE_LIMIT
    assert completion.diagnostics["attempts"] == 3
    assert completion.diagnostics["retry_reasons"] == ["429", "429"]
    assert "rate limit" in (completion.error_message or "").lower()
    assert clock.sleeps == [1.0, 1.0]
    # The wait is in the latency, not invisible.
    assert completion.latency_ms >= 2000


def test_pacing_spaces_requests_to_the_same_model(monkeypatch):
    clock = FakeClock()
    starts: list[float] = []

    def fake_run_chat(*args, **kwargs):
        starts.append(clock.now)
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    paced = provider(clock, intervals={"albert-qwen": 3.75})

    paced.complete(request())
    paced.complete(request())

    assert len(starts) == 2
    assert starts[1] - starts[0] >= 3.75
    assert clock.sleeps == [3.75]


def test_pacing_is_per_origin(monkeypatch):
    clock = FakeClock()

    def fake_run_chat(*args, **kwargs):
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    paced = provider(clock, intervals={"*": 3.75})

    paced.complete(request(origin="albert"))
    paced.complete(request(origin="ragarenn"))
    paced.complete(request(origin="albert"))

    # Only the second albert request waits; the other origin is independent.
    assert clock.sleeps == [3.75]


def test_timeout_then_success_counts_the_wait(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise coach_llm.LLMError("Could not reach M: The read operation timed out")
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    completion = provider(clock).complete(request(timeout_s=60))

    assert completion.status == Status.OK
    assert completion.diagnostics["attempts"] == 2
    assert completion.diagnostics["retry_reasons"] == ["timeout"]
    assert clock.sleeps == [config.RETRY_BASE_DELAY_S]
    assert completion.latency_ms >= int(config.RETRY_BASE_DELAY_S * 1000)


def test_attempt_budget_does_not_reset_between_tries(monkeypatch):
    clock = FakeClock()
    seen: list[float] = []

    def fake_run_chat(*args, **kwargs):
        seen.append(args[3]["timeout_s"])
        if len(seen) == 1:
            clock.now += 30.0  # the first attempt burned half the budget
            raise http_error(503)
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)

    provider(clock).complete(request(timeout_s=60))

    assert len(seen) == 2
    assert seen[0] == 60.0
    assert seen[1] < 60.0, "the second attempt gets what is left of the budget"


def test_a_5xx_is_retried_and_4xx_is_not(monkeypatch):
    clock = FakeClock()

    def fake_run_chat(*args, **kwargs):
        raise http_error(503)

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    server = provider(clock, max_attempts=2).complete(request())
    assert server.diagnostics["attempts"] == 2

    clock = FakeClock()
    calls = {"n": 0}

    def reject(*args, **kwargs):
        calls["n"] += 1
        raise http_error(400)

    monkeypatch.setattr(coach_llm, "run_chat", reject)
    bad = provider(clock).complete(request())
    assert calls["n"] == 1
    assert bad.diagnostics["attempts"] == 1


def test_retry_reason_labels():
    assert retry_reason(http_error(429)) == "429"
    assert retry_reason(http_error(503)) == "503"
    assert retry_reason(http_error(401)) is None
    assert retry_reason(http_error(403)) is None
    assert retry_reason(http_error(404)) is None
    assert retry_reason(http_error(400)) is None
    assert retry_reason(coach_llm.LLMError("M returned an empty response.")) is None
    assert retry_reason(coach_llm.LLMError("Could not reach M: timed out")) == "timeout"


def test_pacer_returns_the_seconds_it_slept():
    clock = FakeClock()
    pacer = Pacer(4.0, clock=clock, sleep=clock.sleep)

    assert pacer.wait() == 0.0
    assert pacer.wait() == 4.0
    assert clock.sleeps == [4.0]


def test_record_round_trip_keeps_attempt_accounting():
    plan = make_plan(fixtures=[make_fixture()])
    completion = make_completion(
        diagnostics={
            "attempts": 3,
            "retried": True,
            "retry_reasons": ["429", "timeout"],
            "retry_wait_ms": 2500,
            "rate_limit_wait_ms": 2000,
        }
    )

    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")

    assert record["attempts"] == 3
    assert record["retried"] is True
    assert record["retry_reasons"] == ["429", "timeout"]
    assert record["retry_wait_ms"] == 2500
    assert record["rate_limit_wait_ms"] == 2000
    assert records.parse_record(records.serialize_record(record)) == record


def test_record_defaults_to_one_attempt():
    plan = make_plan(fixtures=[make_fixture()])
    record = records.build_record(
        plan, plan.items[0], make_completion(), NOW, sweep="test"
    )

    assert record["attempts"] == 1
    assert record["retried"] is False
    assert record["retry_reasons"] == []


def test_provider_is_available_without_a_key_for_local_models():
    """The retry constructor must not change availability's contract."""
    spec = make_spec(
        "ollama", adapter="openai_http", origin="ollama", registry_id="ollama-local"
    )
    assert provider(FakeClock()).availability(spec).status is AvailabilityStatus.OK


def test_availability_is_reported_for_a_disabled_spec():
    spec = make_spec("gone", adapter="openai_http", enabled=False)
    result = provider(FakeClock()).availability(spec)
    assert result.status is AvailabilityStatus.DISABLED


def test_pacing_wait_that_overruns_the_budget_exhausts_without_calling(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    paced = provider(clock, intervals={"albert-qwen": 5.0})

    # The first request opens the pacing window; the second one has to wait
    # 5 s, which is more than the 2 s budget it was given.
    assert paced.complete(request(timeout_s=60.0)).status == Status.OK
    calls["n"] = 0
    completion = paced.complete(request(timeout_s=2.0))

    assert calls["n"] == 0, "the budget is checked after the pacing wait"
    assert completion.status == Status.TIMEOUT
    assert completion.error_kind == ErrorKind.TIMEOUT
    assert completion.diagnostics["budget_exhausted"] is True
    assert "exhausted while pacing" in (completion.error_message or "")


def test_retry_merges_usage_from_a_discarded_attempt(monkeypatch):
    clock = FakeClock()
    calls = {"n": 0}

    def fake_run_chat(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            error = http_error(503)
            error.usage = {
                "prompt_tokens": 50,
                "completion_tokens": 5,
                "total_tokens": 55,
            }
            raise error
        return TRACE

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    spec = make_spec(
        "albert-qwen",
        adapter="openai_http",
        origin="albert",
        model="provider-model",
        registry_id="ollama-local",
        pricing=Pricing(1.0, 2.0),
    )
    req = request()
    req = Request(
        model=spec,
        snapshot=req.snapshot,
        user_message=req.user_message,
        tool_context=req.tool_context,
        timeout_s=req.timeout_s,
    )

    completion = provider(clock).complete(req)

    assert completion.status == Status.OK
    assert completion.usage.prompt_tokens == 150
    assert completion.usage.completion_tokens == 25
    assert completion.usage.total_tokens == 175
    assert completion.cost_usd == 0.0002


def test_tools_rejection_retry_is_counted_as_an_attempt(monkeypatch):
    clock = FakeClock()
    trace = coach_llm.ChatTrace(
        text="Answer without tools.",
        tool_calls=(),
        usage=None,
        rounds=2,
        tools_offered=11,
        tools_dropped=True,
        finish_reason="stop",
        context_chars=500,
        context_truncated=False,
    )
    monkeypatch.setattr(coach_llm, "run_chat", lambda *args, **kwargs: trace)

    completion = provider(clock).complete(request())

    assert completion.status == Status.OK
    assert completion.diagnostics["attempts"] == 2
    assert completion.diagnostics["tool_retries"] == 1
    assert completion.diagnostics["retried"] is True
    assert completion.diagnostics["retry_reasons"] == []
