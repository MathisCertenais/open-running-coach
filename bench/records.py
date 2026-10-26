"""Record schema, serialisation and secret redaction.

A key echoed by a provider must never reach disk or the terminal. Every string
that leaves this module passes through ``redact`` first, and the capture loop
passes the roster's env names in so the redaction set is explicit rather than a
guess about what looks secret.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from . import config
from .plan import BenchmarkPlan, WorkItem, sha256_payload, sha256_text
from .providers.base import Completion, Status

logger = logging.getLogger(__name__)


def secret_values(env_names: Iterable[str]) -> tuple[str, ...]:
    """Read every non-empty value of the roster's key env vars."""
    values = {value for name in env_names if (value := os.environ.get(name))}
    return tuple(sorted(values, key=len, reverse=True))


def redact(text: str, secrets: Sequence[str]) -> str:
    """Replace every occurrence of every known secret value."""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, config.REDACTION_PLACEHOLDER)
    return redacted


def redact_obj(value: object, secrets: Sequence[str]) -> object:
    """Recursively redact strings in a JSON-shaped payload."""
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, Mapping):
        return {key: redact_obj(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_obj(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_obj(item, secrets) for item in value]
    return value


def _utc_timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _usage_payload(completion: Completion) -> Optional[dict]:
    usage = completion.usage
    if not usage.reported:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "source": usage.source,
    }


def _tool_calls_payload(completion: Completion, secrets: Sequence[str]) -> list[dict]:
    payload = []
    for call in completion.tool_calls:
        preview = sha256_payload(call.result)
        rendered = json.dumps(
            redact_obj(call.result, secrets),
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
        )
        payload.append(
            {
                "round": call.round,
                "name": call.name,
                "arguments": redact_obj(dict(call.arguments), secrets),
                "result_sha256": preview,
                "result_preview": rendered[: config.BENCH_PREVIEW_CHARS],
                "ok": call.ok,
            }
        )
    return payload


def build_record(
    plan: BenchmarkPlan,
    item: WorkItem,
    completion: Completion,
    started_at: datetime,
    *,
    sweep: str,
    secrets: Sequence[str] = (),
) -> dict:
    """Turn one completion into the append-only record the report reads."""
    status = completion.status
    answer = redact(completion.text, secrets) if status == Status.OK else ""
    tool_calls = _tool_calls_payload(completion, secrets)
    diagnostics = completion.diagnostics or {}
    error = None
    if completion.error_kind is not None:
        error = {
            "kind": completion.error_kind.value,
            "message": redact(completion.error_message or "", secrets),
        }

    record = {
        "schema_version": config.BENCH_SCHEMA_VERSION,
        "record_id": item.id,
        "sweep": sweep,
        "plan_hash": plan.plan_hash,
        "started_at": _utc_timestamp(started_at),
        "model": {
            "key": item.model.key,
            "adapter": item.model.adapter,
            "origin": item.model.origin,
            "model_id": item.model.model,
            "variant": item.model.variant,
            "cohort": item.model.cohort,
            "params": dict(item.model.params),
            "fidelity": completion.fidelity,
        },
        "fixture": {
            "scenario": item.fixture.scenario,
            "version": item.fixture.version,
            "snapshot_sha256": item.fixture.snapshot_sha256,
            "tool_context_sha256": item.fixture.tool_context_sha256,
        },
        "prompt": {"id": item.prompt.id, "sha256": item.prompt.sha256},
        "repeat": item.repeat,
        "status": status.value,
        "error": error,
        "answer": answer,
        "answer_sha256": sha256_text(answer),
        "answer_chars": len(answer),
        "finish_reason": completion.finish_reason,
        "usage": _usage_payload(completion),
        "cost_usd": completion.cost_usd,
        "cost_source": completion.cost_source,
        "tool_calls": tool_calls,
        "tool_rounds": max((call["round"] for call in tool_calls), default=0),
        "tools_offered": int(diagnostics.get("tools_offered") or 0),
        # What happened on the wire. A call that succeeded on its third try is
        # a success with attempts=3; the retry reasons say why it was asked
        # again, and the waits are wall-clock, not estimates.
        "attempts": int(diagnostics.get("attempts") or 1),
        "retried": bool(diagnostics.get("retried")),
        "retry_reasons": list(diagnostics.get("retry_reasons") or []),
        "retry_wait_ms": int(diagnostics.get("retry_wait_ms") or 0),
        "rate_limit_wait_ms": int(diagnostics.get("rate_limit_wait_ms") or 0),
        "context": {
            "chars": int((completion.context or {}).get("chars") or 0),
            "truncated": bool((completion.context or {}).get("truncated")),
        },
        "latency_ms": completion.latency_ms,
        "latency_kind": completion.latency_kind,
        "notes": list(completion.notes),
    }
    return redact_obj(record, secrets)


def serialize_record(record: Mapping[str, object]) -> str:
    """One compact JSON line; the file is a stream, not a pretty document."""
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def parse_record(line: str) -> dict:
    """Parse one JSONL record, raising ``ValueError`` on a malformed line."""
    parsed = json.loads(line)
    if not isinstance(parsed, dict):
        raise ValueError("a record must be a JSON object")
    return parsed


def append_record(
    path: Path, record: Mapping[str, object], secrets: Sequence[str] = ()
) -> None:
    """Append, flush and fsync one record so a crash cannot lose the answer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_obj(dict(record), secrets)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialize_record(safe) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_records(path: Path) -> Iterator[dict]:
    """Yield records, skipping a truncated tail or a malformed line with a log."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            yield parse_record(line)
        except ValueError:
            if index == len(lines) - 1:
                logger.warning(
                    "Skipping truncated last record in %s (crash during append)",
                    path,
                )
                break
            logger.warning("Skipping malformed record at %s:%d", path, index + 1)


def completed_ids(path: Path) -> set[str]:
    """Ids that already have an ``ok`` answer, the resume key."""
    return {
        record["record_id"]
        for record in read_records(path)
        if record.get("status") == Status.OK.value and record.get("record_id")
    }
