"""Factories shared by the benchmark unit tests."""

from __future__ import annotations

from datetime import datetime, timezone

from bench.plan import Fixture, Prompt, build_plan, sha256_payload, sha256_text
from bench.providers.base import (
    Completion,
    ModelSpec,
    Pricing,
    Status,
    Usage,
)


def make_spec(
    key: str = "model-a",
    *,
    adapter: str = "fake",
    origin: str = "test",
    model: str | None = None,
    cohort: str = "production",
    variant: str | None = None,
    registry_id: str | None = None,
    pricing: Pricing | None = None,
    params: dict | None = None,
    enabled: bool = True,
) -> ModelSpec:
    return ModelSpec(
        key=key,
        adapter=adapter,
        origin=origin,
        model=model or f"{key}-model",
        cohort=cohort,
        variant=variant,
        registry_id=registry_id,
        pricing=pricing,
        params=params if params is not None else {"temperature": 0.4},
        enabled=enabled,
    )


def make_fixture(
    scenario: str = "healthy",
    *,
    version: int = 1,
    snapshot: dict | None = None,
    tool_context: dict | None = None,
) -> Fixture:
    snapshot = snapshot or {"load": {"last_7d": 100}}
    tool_context = tool_context or {"activities": [], "today": "2026-03-01"}
    return Fixture(
        scenario=scenario,
        version=version,
        as_of=tool_context.get("today", "2026-03-01"),
        snapshot=snapshot,
        tool_context=tool_context,
        snapshot_sha256=sha256_payload(snapshot),
        tool_context_sha256=sha256_payload(tool_context),
    )


def make_prompt(prompt_id: str = "this_week", text: str = "What now?") -> Prompt:
    return Prompt(id=prompt_id, text=text, sha256=sha256_text(text))


def make_plan(
    models: list[ModelSpec] | None = None,
    fixtures: list[Fixture] | None = None,
    prompts: list[Prompt] | None = None,
    *,
    repeats: int = 1,
):
    models = models or [make_spec()]
    fixtures = fixtures or [make_fixture()]
    prompts = prompts or [make_prompt()]
    return build_plan(
        models,
        [fixture.ref() for fixture in fixtures],
        prompts,
        repeats,
        0,
        system_prompt_sha256="system-hash",
    )


def make_completion(
    *,
    text: str = "An answer.",
    status: Status = Status.OK,
    error_kind=None,
    error_message: str | None = None,
    usage: Usage | None = None,
    cost_usd: float | None = None,
    cost_source: str | None = None,
    context: dict | None = None,
    diagnostics: dict | None = None,
    notes: tuple[str, ...] = (),
    finish_reason: str | None = "stop",
    fidelity: str = "production",
    latency_kind: str = "http_roundtrip",
) -> Completion:
    return Completion(
        text=text,
        status=status,
        error_kind=error_kind,
        error_message=error_message,
        usage=usage
        if usage is not None
        else Usage(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            source="provider",
        ),
        cost_usd=cost_usd,
        cost_source=cost_source,
        latency_ms=12,
        latency_kind=latency_kind,
        fidelity=fidelity,
        notes=notes,
        diagnostics=diagnostics or {},
        context=context or {"chars": 10, "truncated": False},
        finish_reason=finish_reason,
    )


NOW = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
