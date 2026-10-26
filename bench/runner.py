"""Capture loop: resume, per-record isolation, append to JSONL.

One broken model must not abort a sweep. The provider returns failures as
``Completion`` values; the loop also converts an unexpected exception into a
recorded SERVER failure, per CODING_STANDARDS rule 9.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from . import config
from .plan import BenchmarkPlan, Fixture, WorkItem
from .providers.base import (
    Availability,
    AvailabilityStatus,
    Completion,
    ErrorKind,
    Provider,
    Request,
    Status,
)
from .records import append_record, build_record, completed_ids, read_records, redact

logger = logging.getLogger(__name__)


@dataclass
class CaptureSummary:
    """What one capture pass planned, skipped, attempted and wrote."""

    planned: int = 0
    skipped_existing: int = 0
    skipped_unavailable: int = 0
    attempted: int = 0
    ok: int = 0
    failed: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)
    # Retries are counted per model so a capture that survived a rate limit
    # says so; the wait is the wall clock spent on 429s, not on 5xx backoff.
    retries_by_model: dict[str, int] = field(default_factory=dict)
    retry_reasons: dict[str, int] = field(default_factory=dict)
    rate_limit_wait_s: float = 0.0

    @property
    def every_attempt_failed(self) -> bool:
        """True only when records were attempted and none succeeded."""
        return self.attempted > 0 and self.ok == 0

    def as_dict(self) -> dict:
        """Serialise the counts written to ``meta.json``."""
        return {
            "planned": self.planned,
            "skipped_existing": self.skipped_existing,
            "skipped_unavailable": self.skipped_unavailable,
            "attempted": self.attempted,
            "ok": self.ok,
            "failed": self.failed,
            "by_status": dict(self.by_status),
            "unavailable": dict(self.unavailable),
            "retries_by_model": dict(self.retries_by_model),
            "retry_reasons": dict(self.retry_reasons),
            "rate_limit_wait_s": round(self.rate_limit_wait_s, 3),
        }

    def note_completion(self, key: str, completion: Completion) -> None:
        """Fold one attempt's retry diagnostics into the summary."""
        diagnostics = completion.diagnostics or {}
        if diagnostics.get("retried"):
            self.retries_by_model[key] = self.retries_by_model.get(key, 0) + 1
            for reason in diagnostics.get("retry_reasons") or ():
                label = str(reason)
                self.retry_reasons[label] = self.retry_reasons.get(label, 0) + 1
        self.rate_limit_wait_s += (
            float(diagnostics.get("rate_limit_wait_ms") or 0) / 1000.0
        )


Progress = Callable[[WorkItem, Completion], None]


def _timeout_for(item: WorkItem) -> float:
    value = item.model.params.get("timeout_s")
    if isinstance(value, (int, float)):
        return float(value)
    return config.DEFAULT_TIMEOUT_S


def capture(
    plan: BenchmarkPlan,
    providers: Mapping[str, Provider],
    sweep_directory: Path,
    fixtures: Mapping[str, Fixture],
    *,
    sweep: str,
    force: bool = False,
    keep_raw: bool = False,
    secrets: Sequence[str] = (),
    retry_failures: bool = True,
    progress: Optional[Progress] = None,
) -> CaptureSummary:
    """Run every missing work item and append one record per attempt.

    A provider failure is data. An exception from a provider is a bug in that
    adapter, but it is still isolated to one record so the rest of the sweep is
    written.
    """
    records_path = sweep_directory / config.RECORDS_FILENAME
    existing = {
        record["record_id"]: record.get("status")
        for record in read_records(records_path)
        if record.get("record_id")
    }
    already_ok = completed_ids(records_path)

    summary = CaptureSummary(planned=len(plan.items))
    availability: dict[str, Availability] = {}
    for item in plan.items:
        if item.model.key not in availability:
            provider = providers.get(item.model.adapter)
            if provider is None:
                availability[item.model.key] = Availability(
                    status=AvailabilityStatus.UNKNOWN_ID,
                    detail="no adapter registered",
                )
            else:
                availability[item.model.key] = provider.availability(item.model)
        result = availability[item.model.key]
        if not result.ok:
            summary.skipped_unavailable += 1
            summary.unavailable[item.model.key] = result.status.value
            continue

        if not force:
            if item.id in already_ok:
                summary.skipped_existing += 1
                continue
            if item.id in existing and not retry_failures:
                summary.skipped_existing += 1
                continue

        fixture = fixtures.get(item.fixture.scenario)
        if fixture is None:
            summary.failed += 1
            summary.attempted += 1
            summary.by_status["error"] = summary.by_status.get("error", 0) + 1
            logger.error("Missing fixture %r for %s", item.fixture.scenario, item.id)
            continue

        request = Request(
            model=item.model,
            snapshot=fixture.snapshot,
            user_message=item.prompt.text,
            tool_context=fixture.tool_context,
            timeout_s=_timeout_for(item),
        )
        started_at = datetime.now(timezone.utc)
        provider = providers[item.model.adapter]
        try:
            completion = provider.complete(request)
        except Exception as exc:  # rule 9: logged and converted to a fallback
            message = redact(str(exc), secrets)
            logger.warning(
                "Provider %s raised for %s: %s",
                item.model.adapter,
                item.id,
                message,
            )
            completion = Completion(
                text="",
                status=Status.ERROR,
                error_kind=ErrorKind.SERVER,
                error_message=message,
                latency_kind=(
                    "http_roundtrip"
                    if item.model.cohort == "production"
                    else "cli_process"
                ),
                fidelity=(
                    "production" if item.model.cohort == "production" else "proxy"
                ),
                diagnostics={"raised": True},
                context={"chars": 0, "truncated": False},
            )

        summary.attempted += 1
        summary.by_status[completion.status.value] = (
            summary.by_status.get(completion.status.value, 0) + 1
        )
        summary.note_completion(item.model.key, completion)
        if completion.status == Status.OK:
            summary.ok += 1
        else:
            summary.failed += 1

        record = build_record(
            plan, item, completion, started_at, sweep=sweep, secrets=secrets
        )
        append_record(records_path, record, secrets)
        # A failed CLI call is exactly where the raw event stream matters: the
        # pilot's three ``empty`` records had no transcript, so they could not be
        # diagnosed. Persist raw for every failure, not only under --keep-raw.
        if keep_raw or completion.status != Status.OK:
            _write_raw(sweep_directory, item, completion, secrets)
        if progress is not None:
            progress(item, completion)
    return summary


def _write_raw(
    sweep_directory: Path,
    item: WorkItem,
    completion: Completion,
    secrets: Sequence[str],
) -> None:
    events = (
        completion.diagnostics.get("raw_events") if completion.diagnostics else None
    )
    lines = [redact(str(line), secrets) for line in events or ()]
    # The CLI stream already contains tool events; the HTTP path needs the
    # full results written separately or grounding has only the preview.
    if not events:
        for call in completion.tool_calls:
            lines.append(
                redact(
                    json.dumps(
                        {
                            "round": call.round,
                            "name": call.name,
                            "arguments": dict(call.arguments),
                            "result": dict(call.result),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    secrets,
                )
            )
    if not lines:
        return
    path = sweep_directory / config.RAW_DIRNAME / f"{item.id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
