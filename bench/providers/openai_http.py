"""HTTP adapter: the production coach path.

This adapter calls the same ``coach_llm.run_chat`` that ``chat()`` wraps. It
never shapes messages itself: the system prompt, snapshot serialisation, tool
loop and retry-without-tools fallback stay production concerns.

What the adapter owns is *when to ask again*: a 429, a 5xx or a timeout is
retried with jittered backoff and per-model pacing; a 401/403/404 or an
empty/thinking-only answer is not. Every attempt is recorded, so a call that
succeeded on its third try is a success with ``attempts: 3``, not an error.

A retry repeats the production turn from the start, including any tool rounds
already made. The tools are read-only, so re-running them cannot change the
athlete's data; it only costs the tokens of the earlier rounds.
"""

from __future__ import annotations

import os
import random
import re
import time
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

from app import coach_llm
from app.config import LLM_MAX_TOKENS, LLM_TEMPERATURE

from .. import config
from .base import (
    Availability,
    AvailabilityStatus,
    Completion,
    ErrorKind,
    ModelSpec,
    Request,
    Status,
    ToolCall,
    Usage,
)
from .resilience import (
    AttemptOutcome,
    PacerRegistry,
    RetryPolicy,
    call_with_retry,
    pacing_interval,
    pacing_key,
    retry_after,
    retry_reason,
)

_HTTP_CODE = re.compile(r"HTTP (\d{3})")


def _is_local(base_url: str) -> bool:
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host in config.LOCAL_HOSTS


def _classify(message: str) -> tuple[ErrorKind, Status]:
    """Map a production error string to the harness's failure vocabulary."""
    match = _HTTP_CODE.search(message)
    if match:
        code = int(match.group(1))
        if code in (401, 403):
            return ErrorKind.AUTH, Status.ERROR
        if code == 404:
            return ErrorKind.NOT_FOUND, Status.ERROR
        if code == 429:
            return ErrorKind.RATE_LIMIT, Status.ERROR
        if code == 408:
            return ErrorKind.TIMEOUT, Status.TIMEOUT
        return ErrorKind.SERVER, Status.ERROR
    lowered = message.lower()
    if "hidden reasoning" in lowered:
        return ErrorKind.THINKING_ONLY, Status.ERROR
    if "empty response" in lowered:
        return ErrorKind.EMPTY, Status.EMPTY
    if "timed out" in lowered or "timeout" in lowered:
        return ErrorKind.TIMEOUT, Status.TIMEOUT
    if "could not reach" in lowered:
        return ErrorKind.UNREACHABLE, Status.ERROR
    return ErrorKind.SERVER, Status.ERROR


class OpenAIHTTPProvider:
    """One OpenAI-compatible call per record, through production code."""

    adapter = "openai_http"

    def __init__(
        self,
        *,
        policy: RetryPolicy | None = None,
        intervals: Mapping[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._policy = policy or RetryPolicy()
        # ``None`` means "read bench/config.py"; an explicit mapping (even an
        # empty one) means exactly those intervals, which is what tests pass.
        self._intervals = None if intervals is None else dict(intervals)
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._pacers = PacerRegistry(clock=clock, sleep=sleep)

    def _interval_for(self, spec: ModelSpec) -> float:
        if self._intervals is not None:
            for key in (spec.key, spec.registry_id or ""):
                if key and key in self._intervals:
                    return float(self._intervals[key])
            return float(self._intervals.get("*", 0.0))
        return pacing_interval(spec)

    def availability(self, spec: ModelSpec) -> Availability:
        """Report whether this roster line has an endpoint and a key."""
        if not spec.enabled:
            return Availability(
                AvailabilityStatus.DISABLED,
                spec.disabled_reason or "disabled in the roster",
            )
        if spec.registry_id:
            model = coach_llm.find_model(spec.registry_id)
            if model is None:
                return Availability(
                    AvailabilityStatus.UNKNOWN_ID,
                    f"{spec.registry_id!r} is not in models.json",
                )
            if not model.get("base_url") or not model.get("model"):
                return Availability(
                    AvailabilityStatus.UNKNOWN_ID,
                    f"{spec.registry_id!r} has no base URL or model",
                )
            if model.get("api_key") or _is_local(model["base_url"]):
                return Availability(AvailabilityStatus.OK)
            key_name = model.get("api_key_env") or "API key"
            return Availability(
                AvailabilityStatus.MISSING_KEY, f"{key_name} is not set"
            )
        # A roster-only model: the roster carries the endpoint.
        if not spec.base_url or not spec.model:
            return Availability(
                AvailabilityStatus.UNKNOWN_ID,
                "no registry id and no base_url in the roster",
            )
        if spec.api_key_env and not os.environ.get(spec.api_key_env):
            return Availability(
                AvailabilityStatus.MISSING_KEY, f"{spec.api_key_env} is not set"
            )
        return Availability(AvailabilityStatus.OK)

    def complete(self, request: Request) -> Completion:
        """Run the production chat loop with retry, pacing and a total budget."""
        started_clock = self._clock()
        registry_model = (
            coach_llm.find_model(request.model.registry_id)
            if request.model.registry_id
            else None
        )
        if registry_model is not None:
            # The harness may override the timeout only; every other setting
            # comes from models.json so the benchmark measures what the app
            # sends.
            model = {**registry_model, "headers": dict(request.model.headers)}
        elif request.model.base_url:
            # Roster-only model: the app registry does not carry it, so build
            # the same dict the app would use with its production settings.
            params = request.model.params
            model = {
                "id": request.model.key,
                "name": request.model.label or request.model.key,
                "base_url": request.model.base_url,
                "chat_path": config.PRODUCTION_CHAT_PATH,
                "model": request.model.model,
                "temperature": float(params.get("temperature", LLM_TEMPERATURE)),
                "max_tokens": int(params.get("max_tokens") or LLM_MAX_TOKENS),
                "tools": params.get("tools", True),
                "api_key": os.environ.get(request.model.api_key_env or "", ""),
                "headers": dict(request.model.headers),
                "timeout_s": request.timeout_s,
            }
        else:
            return self._failure(
                request,
                started_clock,
                ErrorKind.NOT_FOUND,
                f"unknown registry id {request.model.registry_id!r}",
            )
        key = pacing_key(request.model)
        interval = self._interval_for(request.model)
        pace_waits: list[float] = []

        def pace() -> None:
            # Pacing runs inside the budget: the retry helper checks the
            # deadline after this, so a wait that overruns exhausts the
            # record instead of starting a call the budget cannot cover.
            pace_waits.append(self._pacers.wait(key, interval))

        def attempt(remaining_s: float):
            timeout = max(config.RETRY_MIN_ATTEMPT_TIMEOUT_S, remaining_s)
            return coach_llm.run_chat(
                dict(request.snapshot),
                [],
                request.user_message,
                {**model, "timeout_s": timeout},
                dict(request.tool_context) if request.tool_context else None,
            )

        outcome = call_with_retry(
            attempt,
            policy=self._policy,
            clock=self._clock,
            sleep=self._sleep,
            retryable=retry_reason,
            retry_after=retry_after,
            budget_s=float(request.timeout_s),
            before_attempt=pace,
            rng=self._rng,
        )
        diagnostics = self._attempt_diagnostics(outcome, pace_waits)
        if outcome.error is not None:
            return self._failure_from_outcome(
                request, started_clock, outcome, diagnostics
            )

        trace = outcome.value
        tool_retries = 1 if trace.tools_dropped else 0
        diagnostics["attempts"] = outcome.attempts + tool_retries
        diagnostics["tool_retries"] = tool_retries
        diagnostics["retried"] = outcome.retried or bool(tool_retries)
        usage = _usage_from_trace(_merge_usage(outcome.usage, trace.usage))
        cost = None
        cost_source = None
        if request.model.pricing is not None and usage.reported:
            cost = request.model.pricing.cost_usd(usage)
            if cost is not None:
                cost_source = f"price_table:{config.PRICE_TABLE_VERSION}"
        notes = []
        if trace.tools_dropped:
            notes.append("tools_rejected")
        if trace.context_truncated:
            notes.append("context_truncated")
        tool_calls = tuple(
            ToolCall(
                round=call.round,
                name=call.name,
                arguments=call.arguments,
                result=call.result,
                ok="error" not in call.result,
            )
            for call in trace.tool_calls
        )
        return Completion(
            text=trace.text,
            status=Status.OK,
            tool_calls=tool_calls,
            usage=usage,
            cost_usd=cost,
            cost_source=cost_source,
            latency_ms=int((self._clock() - started_clock) * 1000),
            latency_kind="http_roundtrip",
            fidelity="production",
            notes=tuple(notes),
            diagnostics={
                "rounds": trace.rounds,
                "tools_offered": trace.tools_offered,
                "tools_dropped": trace.tools_dropped,
                "registry_id": request.model.registry_id,
                "model_name": model.get("name"),
                "pacing_interval_s": interval,
                **diagnostics,
            },
            context={
                "chars": trace.context_chars,
                "truncated": trace.context_truncated,
            },
            finish_reason=trace.finish_reason,
        )

    @staticmethod
    def _attempt_diagnostics(outcome: AttemptOutcome, pace_waits: list[float]) -> dict:
        return {
            "attempts": outcome.attempts,
            "retried": outcome.retried,
            "retry_reasons": list(outcome.reasons),
            "retry_wait_ms": int(round(outcome.wait_s * 1000)),
            "rate_limit_wait_ms": int(round(outcome.wait_for("429") * 1000)),
            "pace_wait_ms": int(round(sum(pace_waits) * 1000)),
            "budget_exhausted": outcome.budget_exhausted,
        }

    def _failure_from_outcome(
        self,
        request: Request,
        started_clock: float,
        outcome: AttemptOutcome,
        diagnostics: dict,
    ) -> Completion:
        error = outcome.error
        assert error is not None
        kind, status = _classify(str(error))
        message = str(error)
        if (
            kind is ErrorKind.RATE_LIMIT
            and outcome.attempts >= self._policy.max_attempts
        ):
            message = (
                f"rate limit: gave up after {outcome.attempts} attempts ({message})"
            )
        elif outcome.budget_exhausted:
            message = (
                f"{message} (timeout budget exhausted after "
                f"{outcome.attempts} attempt(s))"
            )
        return self._failure(
            request,
            started_clock,
            kind,
            message,
            status=status,
            notes=("tools_rejected",) if "HTTP 400" in str(error) else (),
            diagnostics=diagnostics,
        )

    def _failure(
        self,
        request: Request,
        started_clock: float,
        kind: ErrorKind,
        message: str,
        *,
        status: Status = Status.ERROR,
        notes: tuple[str, ...] = (),
        diagnostics: Optional[dict] = None,
    ) -> Completion:
        return Completion(
            text="",
            status=status,
            error_kind=kind,
            error_message=message,
            latency_ms=int((self._clock() - started_clock) * 1000),
            latency_kind="http_roundtrip",
            fidelity="production",
            notes=notes,
            diagnostics={
                "registry_id": request.model.registry_id,
                **(diagnostics or {}),
            },
        )


def _merge_usage(discarded: tuple[Mapping[str, object], ...], latest) -> dict | None:
    """Sum the usage a failed attempt reported with the successful attempt's.

    A retry must not erase tokens the provider already billed. Today only the
    successful trace reports usage, but the loop carries any counts an
    exception exposes so a future transport can surface partial usage without
    the cost silently disappearing.
    """
    total: dict[str, object] = dict(latest) if isinstance(latest, Mapping) else {}
    for payload in discarded:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                current = total.get(key)
                total[key] = (current if isinstance(current, int) else 0) + value
    return total or None


def _usage_from_trace(raw: Optional[dict]) -> Usage:
    if not isinstance(raw, dict):
        return Usage(source="unknown")
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    total = raw.get("total_tokens")
    if prompt is None and completion is None:
        return Usage(source="unknown")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return Usage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
        total_tokens=total if isinstance(total, int) else None,
        source="provider",
    )
