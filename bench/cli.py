"""Command-line entry point: the only module that decides to spend money.

Phases 0-2 implement ``fixtures``, ``providers`` and ``capture``. Scoring,
reporting and judging are separate passes added later; this module deliberately
has no code path that calls a model unless ``capture`` is run without
``--dry-run``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from app import coach_llm

from . import config, records
from .fixtures import load_fixtures, load_prompts, verify_frozen
from .fixtures.scenarios import SCENARIOS
from .plan import BenchmarkPlan, Fixture, Prompt, build_plan, sha256_text, sweep_dir
from .providers import ADAPTERS
from .providers.base import ModelSpec, Pricing, Status, Usage
from .roster import (
    Roster,
    availability_map,
    load_roster,
    select_specs,
)
from .runner import CaptureSummary, capture

if TYPE_CHECKING:  # pragma: no cover - import for annotations only
    from .scoring.rubric import Rubric


def _flatten(values: Sequence[str] | None, default: str = "all") -> list[str]:
    if not values:
        return [default]
    flat: list[str] = []
    for value in values:
        flat.extend(part.strip() for part in value.split(",") if part.strip())
    return flat or [default]


def _select_prompts(prompts: Sequence[Prompt], names: Sequence[str]) -> list[Prompt]:
    if list(names) == ["all"]:
        return list(prompts)
    by_id = {prompt.id: prompt for prompt in prompts}
    unknown = [name for name in names if name not in by_id]
    if unknown:
        raise ValueError(
            f"unknown prompt(s): {', '.join(unknown)}. Known: {', '.join(by_id)}"
        )
    return [by_id[name] for name in names]


def _select_scenarios(names: Sequence[str]) -> list[str]:
    if list(names) == ["all"]:
        return list(SCENARIOS)
    return list(names)


def _fixture_map(fixtures: Iterable[Fixture]) -> dict[str, Fixture]:
    return {fixture.scenario: fixture for fixture in fixtures}


def _secrets(roster: Roster) -> tuple[str, ...]:
    return records.secret_values(roster.secret_env_names)


def _redacted(text: str, secrets: Sequence[str]) -> str:
    return records.redact(text, secrets)


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=config.GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _rubric_payload(rubric: Rubric) -> dict:
    """The rubric file with its hash, as ``meta.json`` must carry it."""
    return {
        "version": rubric.version,
        "source": rubric.source,
        "sha256": rubric.sha256,
        "text": rubric.text,
    }


def _meta_payload(
    roster: Roster,
    plan: BenchmarkPlan,
    prompts: Sequence[Prompt],
    availability: dict,
    counts: dict | None,
    rubric: Rubric | None = None,
) -> dict:
    return {
        "schema_version": config.BENCH_SCHEMA_VERSION,
        "sweep": None,
        "generated_at": _now(),
        "git_sha": _git_sha(),
        "plan": plan.as_dict(),
        "prices_as_of": roster.prices_as_of,
        "roster": str(roster.path.relative_to(config.REPO_ROOT))
        if roster.path.is_relative_to(config.REPO_ROOT)
        else str(roster.path),
        "availability": availability,
        "system_prompt": {
            "text": coach_llm.SYSTEM_PROMPT,
            "sha256": sha256_text(coach_llm.SYSTEM_PROMPT),
        },
        "prompts": [
            {"id": prompt.id, "text": prompt.text, "sha256": prompt.sha256}
            for prompt in prompts
        ],
        "rubric": _rubric_payload(rubric) if rubric is not None else None,
        "judge_model": plan.judge_model,
        "counts": counts,
    }


def _estimated_cost(spec: ModelSpec, calls: int) -> float | None:
    pricing: Pricing | None = spec.pricing
    if pricing is None:
        return None
    usage = Usage(
        prompt_tokens=config.DRY_RUN_ESTIMATE_PROMPT_TOKENS,
        completion_tokens=config.DRY_RUN_ESTIMATE_COMPLETION_TOKENS,
        source="provider",
    )
    per_call = pricing.cost_usd(usage)
    return None if per_call is None else round(per_call * calls, 6)


def _existing_by_model(records_path: Path, plan_hash: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for record in records.read_records(records_path):
        if record.get("plan_hash") != plan_hash:
            continue
        if record.get("status") == Status.OK.value:
            key = (record.get("model") or {}).get("key")
            if key:
                counts[key] += 1
    return counts


def _records_by_model(records_path: Path, plan_hash: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "failed": 0})
    for record in records.read_records(records_path):
        if record.get("plan_hash") != plan_hash:
            continue
        key = (record.get("model") or {}).get("key")
        if not key:
            continue
        bucket = "ok" if record.get("status") == Status.OK.value else "failed"
        counts[key][bucket] += 1
    return dict(counts)


def _print_model_summary(
    plan: BenchmarkPlan,
    records_path: Path,
    availability: dict,
) -> None:
    counts = _records_by_model(records_path, plan.plan_hash)
    for spec in plan.models:
        planned = sum(1 for item in plan.items if item.model.key == spec.key)
        result = availability.get(spec.key)
        if result is not None and not result.ok:
            print(f"  {spec.key}: skipped ({result.status.value}), planned {planned}")
            continue
        model_counts = counts.get(spec.key, {"ok": 0, "failed": 0})
        print(
            f"  {spec.key}: ok {model_counts['ok']}/{planned}, "
            f"failed {model_counts['failed']}"
        )


def _duration(seconds: float) -> str:
    """``93.4`` -> ``1m 33s``; a dry run must not print bare seconds."""
    total = int(round(max(0.0, seconds)))
    minutes, sec = divmod(total, 60)
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _pacing_note(spec: ModelSpec) -> tuple[float, str]:
    """The configured interval and a human explanation of where it came from."""
    from .providers.resilience import pacing_interval

    interval = pacing_interval(spec)
    if interval <= 0:
        return 0.0, "unpaced"
    budget = config.PACING_BUDGETS.get(spec.key)
    if not budget:
        return interval, f"{interval:g} s between requests"
    per_minute = 60.0 / interval
    return interval, (
        f"{interval:g} s between requests ("
        f"{budget['input_tokens_per_min']:,.0f} input tokens/min, "
        f"{budget['requests_per_min']:,.0f} req/min; "
        f"~{per_minute:.1f} calls/min at "
        f"{config.PACING_SNAPSHOT_TOKENS:,} tokens)"
    )


def _print_dry_run(
    plan: BenchmarkPlan,
    availability: dict,
    already_paid: dict[str, int],
    quiet: bool,
) -> None:
    print(f"plan hash: {plan.plan_hash}")
    print(f"planned calls: {len(plan.items)}")
    total_cost = 0.0
    total_known = True
    total_remaining = 0
    pacing_floor = 0.0
    pacing_lines: list[str] = []
    for spec in plan.models:
        planned = sum(1 for item in plan.items if item.model.key == spec.key)
        paid = already_paid.get(spec.key, 0)
        availability_status = availability.get(spec.key)
        status = availability_status.status.value if availability_status else "unknown"
        available = bool(availability_status and availability_status.ok)
        remaining = max(0, planned - paid) if available else 0
        total_remaining += remaining
        interval, note = _pacing_note(spec)
        if available and interval > 0:
            pacing_floor += remaining * interval
            pacing_lines.append(f"  {spec.key}: {remaining} call(s), {note}")
        cost = _estimated_cost(spec, remaining) if available else None
        if not available:
            cost_text = "n/a"
        elif cost is None:
            cost_text = "unknown"
            total_known = False
        else:
            cost_text = f"${cost:.4f}"
            total_cost += cost
        if not quiet:
            print(
                f"  {spec.key:<24} {spec.cohort:<10} {spec.adapter:<12} "
                f"{status:<14} planned={planned:<4} paid={paid:<4} "
                f"remaining={remaining:<4} estimated={cost_text}"
            )
    if pacing_lines:
        print("pacing:")
        for line in pacing_lines:
            print(line)
        print(f"estimated pacing floor: {_duration(pacing_floor)}")
    else:
        print("pacing: no model has a configured rate limit")
    print(f"already paid calls: {sum(already_paid.values())}")
    print(f"calls remaining: {total_remaining}")
    if total_known:
        print(f"estimated cost remaining: ${total_cost:.4f}")
    else:
        print("estimated cost remaining: unknown for at least one model")
    print("dry run: no network calls made")


def _availability_payload(availability: dict) -> dict:
    return {
        key: {"status": result.status.value, "detail": result.detail}
        for key, result in availability.items()
    }


def _command_fixtures(args: argparse.Namespace) -> int:
    prompts = load_prompts()
    if args.check:
        failures = verify_frozen(version=args.version)
        if failures:
            for failure in failures:
                print(f"FAIL {failure}")
            return 1
        print(
            f"fixtures ok: {len(SCENARIOS)} scenarios, "
            f"v{args.version}, {len(prompts)} prompts"
        )
        return 0
    for name in SCENARIOS:
        fixture = load_fixtures([name], args.version)[0]
        print(
            f"{name}.v{fixture.version} as_of={fixture.as_of} "
            f"snapshot={fixture.snapshot_sha256[:12]} "
            f"tool_context={fixture.tool_context_sha256[:12]}"
        )
    print(f"prompts: {', '.join(prompt.id for prompt in prompts)}")
    return 0


def _command_providers(args: argparse.Namespace) -> int:
    roster = load_roster(args.roster, timeout_s=args.timeout_s)
    availability = availability_map(roster.specs)
    secrets = _secrets(roster)
    for spec in roster.specs:
        result = availability[spec.key]
        detail = _redacted(result.detail, secrets)
        print(
            f"{spec.key:<24} {spec.cohort:<10} {spec.adapter:<12} "
            f"{result.status.value:<14} {detail}"
        )
    ok = sum(1 for result in availability.values() if result.ok)
    print(f"{ok} of {len(roster.specs)} models available")
    return 0


def _archive_records(records_path: Path, old_plan_hash: str) -> Path | None:
    """Move a replaced sweep's records aside instead of mixing two plans.

    ``--force`` replaces a sweep. Appending plan B's records to plan A's file
    would let scoring read both while the report header names only B, so the
    old stream is renamed to ``records.<old plan hash>.jsonl.bak`` and is never
    read again by ``score`` or ``report``.
    """
    if not records_path.exists():
        return None
    label = re.sub(r"[^0-9A-Za-z]", "", old_plan_hash)
    target = records_path.with_name(
        f"{records_path.stem}.{label or 'unknown'}{records_path.suffix}.bak"
    )
    records_path.replace(target)
    return target


def _command_capture(args: argparse.Namespace) -> int:
    from .scoring.rubric import load_rubric

    roster = load_roster(args.roster, timeout_s=args.timeout_s)
    secrets = _secrets(roster)
    model_names = _flatten(args.models)
    try:
        specs = select_specs(roster, model_names)
        prompts = _select_prompts(load_prompts(), _flatten(args.prompts))
        scenario_names = _select_scenarios(_flatten(args.scenarios))
        fixtures = load_fixtures(scenario_names, args.fixture_version)
        rubric = load_rubric(args.rubric)
    except ValueError as exc:
        print(_redacted(str(exc), secrets), file=sys.stderr)
        return 2

    # The rubric hash and the judge model are part of comparability (spec §6):
    # two answers scored under different rubrics, or judged by different
    # models, are not the same measurement even when the prompt is identical.
    plan = build_plan(
        specs,
        [fixture.ref() for fixture in fixtures],
        prompts,
        args.repeats,
        args.seed,
        rubric_hash=rubric.sha256,
        judge_model=args.judge_model,
        system_prompt_sha256=sha256_text(coach_llm.SYSTEM_PROMPT),
    )
    availability = availability_map(specs)
    output_dir = sweep_dir(args.root, args.sweep)
    records_path = output_dir / config.RECORDS_FILENAME
    already_paid = _existing_by_model(records_path, plan.plan_hash)

    if args.dry_run:
        _print_dry_run(plan, availability, already_paid, args.quiet)
        return 0

    meta_path = output_dir / config.META_FILENAME
    previous_hash = None
    if meta_path.exists():
        previous = json.loads(meta_path.read_text(encoding="utf-8"))
        previous_hash = (previous.get("plan") or {}).get("plan_hash")
    record_hashes = {
        str(record.get("plan_hash"))
        for record in records.read_records(records_path)
        if record.get("plan_hash")
    }
    foreign = sorted(record_hashes - {plan.plan_hash})
    if (previous_hash and previous_hash != plan.plan_hash) or foreign:
        if not args.force:
            print(
                "refusing to reuse sweep "
                f"{args.sweep!r}: it holds plan hash "
                f"{previous_hash or ', '.join(foreign)}, this plan is "
                f"{plan.plan_hash}. Use --force to replace the sweep.",
                file=sys.stderr,
            )
            return 2
        archived = _archive_records(records_path, previous_hash or foreign[0])
        if archived is not None and not args.quiet:
            print(
                f"replacing sweep {args.sweep!r}: old records archived to "
                f"{archived.name}"
            )

    meta = _meta_payload(
        roster, plan, prompts, _availability_payload(availability), None, rubric
    )
    meta["sweep"] = args.sweep
    _write_json(meta_path, meta)

    if not args.quiet:
        ok_count = sum(1 for result in availability.values() if result.ok)
        print(
            f"sweep {args.sweep}: {len(plan.items)} planned calls, "
            f"{ok_count} of {len(specs)} models available"
        )
        for key, result in availability.items():
            if not result.ok:
                print(
                    f"  unavailable {key}: {result.status.value} "
                    f"({_redacted(result.detail, secrets)})"
                )

    def progress(item, completion) -> None:
        if args.quiet:
            return
        print(
            f"  {item.model.key} {item.fixture.scenario}/{item.prompt.id} "
            f"r{item.repeat}: {completion.status.value}",
            flush=True,
        )

    summary: CaptureSummary = capture(
        plan,
        ADAPTERS,
        output_dir,
        _fixture_map(fixtures),
        sweep=args.sweep,
        force=args.force,
        keep_raw=args.keep_raw,
        secrets=secrets,
        retry_failures=not args.no_retry_failures,
        progress=progress,
    )

    meta["counts"] = summary.as_dict()
    meta["completed_at"] = _now()
    _write_json(meta_path, meta)

    print(
        f"capture {args.sweep}: attempted {summary.attempted}, "
        f"ok {summary.ok}, failed {summary.failed}, "
        f"skipped {summary.skipped_existing + summary.skipped_unavailable}"
    )
    if summary.retries_by_model:
        print(
            "retries: "
            + ", ".join(
                f"{key} {count}"
                for key, count in sorted(summary.retries_by_model.items())
            )
        )
    else:
        print("retries: none")
    if summary.retry_reasons:
        print(
            "  reasons: "
            + ", ".join(
                f"{reason} x{count}"
                for reason, count in sorted(summary.retry_reasons.items())
            )
        )
    print(f"rate-limit wait: {summary.rate_limit_wait_s:.1f} s")
    _print_model_summary(plan, records_path, availability)
    for status, count in sorted(summary.by_status.items()):
        print(f"  {status}: {count}")
    return 1 if summary.every_attempt_failed else 0


def _sweep_directory(args: argparse.Namespace) -> Path | None:
    return args.sweep_dir or (sweep_dir(args.root, args.sweep) if args.sweep else None)


def _judge_client(
    args: argparse.Namespace,
    records_rows: Sequence[dict],
    judge_config: dict | None = None,
):
    """Build the judge client, or ``None`` when ``--judge`` was not given.

    A judge may be registered entirely from flags — ``--judge-base-url``,
    ``--judge-model`` and ``--judge-key-env`` — so a model that is not in the
    app's ``models.json`` (Albert's gpt-oss-120b) can judge without a registry
    entry.
    """
    from .scoring.judge import refuse_self_judging
    from .scoring.judge_client import OpenAICompatibleJudgeClient

    if not args.judge:
        return None
    judge_id = str(args.judge)
    base_url = args.judge_base_url
    model = args.judge_model
    key_env = args.judge_key_env
    if not base_url:
        registry = coach_llm.find_model(judge_id)
        if registry is None:
            raise ValueError(
                f"judge {judge_id!r} is not in models.json; pass --judge-base-url "
                "(and optionally --judge-model/--judge-key-env)"
            )
        base_url = registry["base_url"]
        model = model or registry.get("model")
        key_env = key_env or registry.get("api_key_env")
    if not base_url:
        raise ValueError("the judge has no base URL")
    under_test: list[object] = []
    for record in records_rows:
        payload = record.get("model") or {}
        under_test.extend(payload.get(field) for field in ("key", "model_id"))
    refuse_self_judging([judge_id, model or ""], under_test)
    judge_config = judge_config or {}
    return OpenAICompatibleJudgeClient(
        model_id=judge_id,
        base_url=str(base_url),
        model=str(model) if model else None,
        key_env=str(key_env) if key_env else None,
        timeout_s=args.judge_timeout_s,
        temperature=float(judge_config.get("temperature", config.JUDGE_TEMPERATURE)),
        # The transport budget is bench config, with the rubric's value as a
        # floor: the 700-token default in rubric.json is what starved the
        # thinking judge, and that is a transport fix, not a rubric change.
        max_tokens=max(
            int(judge_config.get("max_tokens") or 0), config.JUDGE_MAX_TOKENS
        ),
    )


def _judge_secret_values(args: argparse.Namespace) -> list[str]:
    """The judge's resolved key values, from every source.

    ``_judge_client`` resolves the key env from ``models.json`` when the judge
    is a registry entry, so ``--judge-key-env`` alone is not the whole set: the
    registry's ``apiKeyEnv`` (and any inline resolved key) must be redacted too,
    whether or not the base URL came from the registry.
    """
    names: list[str] = []
    values: list[str] = []
    if getattr(args, "judge_key_env", None):
        names.append(str(args.judge_key_env))
    for judge_id in (
        getattr(args, "judge", None),
        getattr(args, "judge_model", None),
    ):
        if not judge_id:
            continue
        entry = coach_llm.find_model(str(judge_id))
        if not entry:
            continue
        if entry.get("api_key_env"):
            names.append(str(entry["api_key_env"]))
        if entry.get("api_key"):
            values.append(str(entry["api_key"]))
    return list(records.secret_values(names)) + values


def _score_secrets(args: argparse.Namespace) -> tuple[str, ...]:
    """Every key value scoring may echo: the roster's and the judge's.

    The judge call is the one place in ``score`` that talks to a provider, so
    its key must be redacted alongside the roster keys even though the judge is
    not a model under test. The judge is resolved exactly as ``_judge_client``
    resolves it, so a registry-provided ``apiKeyEnv`` is covered.
    """
    names: list[str] = []
    try:
        names.extend(load_roster().secret_env_names)
    except (OSError, ValueError):
        # A missing roster must not stop an offline rescore; it only narrows
        # the redaction set to the judge key below.
        pass
    values = set(records.secret_values(names))
    for value in _judge_secret_values(args):
        if not value:
            continue
        values.add(value)
    return tuple(sorted(values, key=len, reverse=True))


def _consistency_problems(
    directory: Path,
    rubric: Rubric,
    judge_id: str | None,
    record_rows: Sequence[dict],
) -> list[str]:
    """Why this records file may not be scored under this rubric/judge.

    Comparability is the plan hash (spec §6). Records from two plans in one
    file, a rubric that moved since capture, or a different judge than the plan
    named all mean the stored answers and the new scores describe different
    measurements.
    """
    problems: list[str] = []
    plan_hashes = sorted(
        {str(row.get("plan_hash")) for row in record_rows if row.get("plan_hash")}
    )
    meta_path = directory / config.META_FILENAME
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
    header_hash = plan.get("plan_hash")
    if len(plan_hashes) > 1:
        problems.append(f"records.jsonl mixes plan hashes {plan_hashes}")
    elif header_hash and plan_hashes and plan_hashes[0] != header_hash:
        problems.append(
            f"records carry plan hash {plan_hashes[0]}, meta.json names {header_hash}"
        )
    if plan.get("rubric_hash") and plan["rubric_hash"] != rubric.sha256:
        problems.append(
            f"the sweep was captured under rubric {plan['rubric_hash']}, the "
            f"current rubric is {rubric.sha256} ({rubric.version})"
        )
    elif header_hash and not plan.get("rubric_hash"):
        # A sweep captured before the plan hash covered the rubric cannot show
        # which rubric it belongs to. Scoring it silently is the defect this
        # guard exists to stop; the flag makes it an explicit audit decision.
        problems.append(
            "meta.json records no rubric hash, so this sweep cannot be shown to "
            f"belong to rubric {rubric.sha256} ({rubric.version})"
        )
    if plan.get("judge_model") and judge_id and plan["judge_model"] != judge_id:
        problems.append(
            f"the plan names judge {plan['judge_model']}, this run uses {judge_id}"
        )
    return problems


def _command_score(args: argparse.Namespace) -> int:
    """Rescore a sweep from ``records.jsonl``; never calls a model under test."""
    from .scoring import aggregate, load_rubric, score_records, write_scores
    from .scoring import judge as judge_module
    from .scoring.judge import judge_answer, judge_prompt_sha256, load_tool_results
    from .scoring.rubric import prompt_text

    directory = _sweep_directory(args)
    if directory is None:
        print("error: give a sweep directory or --sweep <slug>", file=sys.stderr)
        return 2
    records_path = directory / config.RECORDS_FILENAME
    if not records_path.exists():
        print(f"error: no {config.RECORDS_FILENAME} in {directory}", file=sys.stderr)
        return 2
    secrets = _score_secrets(args)
    rubric = load_rubric(args.rubric)
    record_rows = list(records.read_records(records_path))

    problems = _consistency_problems(directory, rubric, args.judge, record_rows)
    if problems:
        message = (
            "refusing to score this sweep: "
            + "; ".join(problems)
            + ". Rescore with the rubric/judge it was captured under, or pass "
            "--allow-stale to score across the difference."
        )
        if not args.allow_stale:
            print(_redacted("error: " + message, secrets), file=sys.stderr)
            return 2
        if not args.quiet:
            print("WARNING stale: " + _redacted(message, secrets), file=sys.stderr)

    fixtures = {}
    hashes_by_scenario: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"snapshot": set(), "tool_context": set()}
    )
    for record in record_rows:
        if record.get("status") != Status.OK.value:
            continue
        fixture_meta = record.get("fixture") or {}
        scenario = str(fixture_meta.get("scenario") or "")
        version = int(fixture_meta.get("version") or config.FIXTURE_VERSION)
        if not scenario:
            continue
        hashes_by_scenario[scenario]["snapshot"].add(
            str(fixture_meta.get("snapshot_sha256") or "")
        )
        hashes_by_scenario[scenario]["tool_context"].add(
            str(fixture_meta.get("tool_context_sha256") or "")
        )
        key = (scenario, version)
        if key in fixtures:
            continue
        try:
            fixtures[key] = load_fixtures([scenario], version)[0]
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    for (scenario, _version), fixture in fixtures.items():
        recorded = hashes_by_scenario.get(scenario, {})
        for label, present, recorded_hashes in (
            ("snapshot", fixture.snapshot_sha256, recorded.get("snapshot") or set()),
            (
                "tool context",
                fixture.tool_context_sha256,
                recorded.get("tool_context") or set(),
            ),
        ):
            expected = {value for value in recorded_hashes if value}
            if expected and present not in expected:
                print(
                    f"error: {scenario} {label} hash {present} does not match the "
                    "records; the sweep was captured on a different fixture",
                    file=sys.stderr,
                )
                return 2
    by_scenario = {
        scenario: fixture for (scenario, _version), fixture in fixtures.items()
    }

    raw_dir = directory / config.RAW_DIRNAME
    resolved_raw = raw_dir if raw_dir.exists() else None
    client = _judge_client(args, record_rows, rubric.judge)
    judge_meta: dict | None = None
    judge_run: dict | None = None
    prompt_sha = None
    if client is not None:
        # The calibration set names its own scenarios; a one-scenario sweep
        # still needs the healthy fixture for the gate.
        calibration_fixtures = dict(by_scenario)
        for answer in judge_module.load_calibration()["answers"]:
            scenario = str(answer.get("scenario") or "")
            if scenario and scenario not in calibration_fixtures:
                calibration_fixtures[scenario] = load_fixtures(
                    [scenario], config.FIXTURE_VERSION
                )[0]
        calibration = judge_module.run_calibration(
            client, rubric.judge, calibration_fixtures
        )
        if not calibration.passed:
            print(
                f"error: the judge failed its pre-run calibration gate "
                f"({calibration.gate}); no verdict will be produced",
                file=sys.stderr,
            )
            for reason in calibration.reasons:
                print(_redacted(f"  {reason}", secrets), file=sys.stderr)
            failed = {name for name, ok in calibration.conditions.items() if not ok}
            if not calibration.reasons and failed:
                print(
                    f"  failed conditions: {', '.join(sorted(failed))}", file=sys.stderr
                )
            return 2
        prompt_sha = judge_prompt_sha256(rubric.judge)
        judge_meta = {
            "model": calibration.judge_model,
            "prompt_sha256": prompt_sha,
        }
        judge_run = {
            **judge_meta,
            "gate": calibration.gate,
            "max_tokens": config.JUDGE_MAX_TOKENS,
            "conditions": dict(calibration.conditions),
            "reasons": list(calibration.reasons),
            "worst_bias": calibration.worst_bias,
            "within_one": calibration.within_one,
            "total_pairs": calibration.total_pairs,
            "calibration": {
                "passed": calibration.passed,
                "gate": calibration.gate,
                "conditions": dict(calibration.conditions),
                "answers": list(calibration.details),
            },
        }
        if not args.quiet:
            print(
                f"judge {calibration.judge_model} certified under "
                f"{calibration.gate} (prompt {prompt_sha[:12]}, "
                f"{calibration.within_one}/{calibration.total_pairs} medians "
                "within ±1)"
            )

    judge_repeats = args.judge_repeats
    judge_scenarios = (
        {part.strip() for part in str(args.judge_scenarios).split(",") if part.strip()}
        if args.judge_scenarios
        else None
    )

    def judge_scorer(record, fixture):
        repeat = int(record.get("repeat") or 0)
        scenario = str((record.get("fixture") or {}).get("scenario") or "")
        if judge_repeats is not None and repeat != judge_repeats:
            # Cost control: judge one repeat per cell. The cell is marked
            # judge_missing and excluded, never imputed (rubric §8.4).
            return {
                "judge_dimensions": None,
                "judge_status": "judge_missing",
                "judge_meta": {
                    "skipped": "judge-repeats",
                    "wanted": judge_repeats,
                    "calls": 0,
                },
            }
        if judge_scenarios is not None and scenario not in judge_scenarios:
            return {
                "judge_dimensions": None,
                "judge_status": "judge_missing",
                "judge_meta": {"skipped": "judge-scenarios", "calls": 0},
            }
        cell = judge_answer(
            record,
            fixture,
            prompt_text(str((record.get("prompt") or {}).get("id") or "")),
            client,
            rubric.judge,
            tool_results=load_tool_results(resolved_raw, record),
        )
        return {
            "judge_dimensions": cell.dimensions,
            "judge_status": cell.status,
            "judge_meta": {
                **(judge_meta or {}),
                "max_tokens": config.JUDGE_MAX_TOKENS,
                "calls": cell.calls,
                "attempts": len(cell.call_log),
                "call_log": [
                    {
                        "max_tokens": call.max_tokens,
                        "finish_reason": call.finish_reason,
                        "reasoning_chars": call.reasoning_chars,
                        "outcome": call.outcome,
                    }
                    for call in cell.call_log
                ],
                "reply_sha256": list(cell.reply_sha256),
                "detail": _redacted(cell.detail, secrets),
            },
        }

    entries = score_records(
        record_rows,
        rubric,
        by_scenario,
        raw_dir=resolved_raw,
        judge_scorer=judge_scorer if client is not None else None,
    )
    output = args.output or (directory / config.SCORES_FILENAME)
    write_scores(output, records.redact_obj(entries, secrets))
    if judge_run is not None:
        meta_path = directory / config.META_FILENAME
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["judge"] = records.redact_obj(judge_run, secrets)
            meta["judge_model"] = judge_run["model"]
            _write_json(meta_path, meta)
    summary = aggregate(
        entries,
        rubric,
        judge_model=(judge_meta or {}).get("model") if judge_meta else None,
        judge_prompt_sha256=prompt_sha,
    )

    if not args.quiet:
        scored = sum(1 for entry in entries if entry.get("scored"))
        print(
            f"scored {scored}/{len(entries)} records with rubric {rubric.version} "
            f"({len(rubric.rules)} rules) -> {output}"
        )
        if rubric.unknown_rules:
            print(
                "WARNING unknown rules (no implementation): "
                + ", ".join(rubric.unknown_rules)
            )
        for model in summary["models"]:
            print(
                f"  {model['key']:<24} {model['cohort']:<10} "
                f"answers={model['answers']:<3} blockers={model['blockers']:<3} "
                f"R={model['r_median']} gate={model['gate_pass_rate']:.2f} "
                f"coverage={model['coverage_mean']}"
                + (
                    "  [insufficient evidence]"
                    if model["insufficient_evidence"]
                    else ""
                )
            )
        print("no model calls made: scoring reads records.jsonl only")
    return 0


def _command_report(args: argparse.Namespace) -> int:
    """Render ``report.md``/``report.json`` from the stored scores."""
    from .report import build_report, write_report
    from .scoring import load_rubric

    directory = _sweep_directory(args)
    if directory is None:
        print("error: give a sweep directory or --sweep <slug>", file=sys.stderr)
        return 2
    if not (directory / config.SCORES_FILENAME).exists():
        print(
            f"error: no {config.SCORES_FILENAME} in {directory}; run `score` first",
            file=sys.stderr,
        )
        return 2
    report = build_report(
        directory, load_rubric(args.rubric), allow_stale=args.allow_stale
    )
    markdown, payload = write_report(directory, report)
    if not args.quiet:
        if report.get("stale"):
            print(
                "WARNING stale scores: "
                + ", ".join(sorted(report["stale"]))
                + " differ from the current header; the report carries a banner"
            )
        print(f"report: {markdown}")
        print(f"data:   {payload}")
        for item in report["insufficient_evidence"]:
            print(
                f"  {item['model']}: insufficient evidence ("
                + "; ".join(item["reasons"])
                + ")"
            )
        for model in report["models"]:
            if model.get("disabled"):
                print(f"  {model['key']}: disabled, not scored")
        print("no model calls made: the report reads stored scores only")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bench.cli", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fixtures = subparsers.add_parser(
        "fixtures", help="List or verify the frozen fixtures."
    )
    fixtures.add_argument("--check", action="store_true")
    fixtures.add_argument("--version", type=int, default=config.FIXTURE_VERSION)
    fixtures.set_defaults(func=_command_fixtures)

    providers = subparsers.add_parser(
        "providers", help="Show roster availability without calling a model."
    )
    providers.add_argument("--roster", type=Path, default=None)
    providers.add_argument("--timeout-s", type=float, default=config.DEFAULT_TIMEOUT_S)
    providers.set_defaults(func=_command_providers)

    capture = subparsers.add_parser(
        "capture", help="Capture answers into bench/data/sweeps/<slug>."
    )
    capture.add_argument("--roster", type=Path, default=None)
    capture.add_argument("--models", nargs="+", default=["all"])
    capture.add_argument("--prompts", nargs="+", default=["all"])
    capture.add_argument("--scenarios", nargs="+", default=["all"])
    capture.add_argument("--sweep", default=config.DEFAULT_SWEEP)
    capture.add_argument("--root", type=Path, default=config.DATA_ROOT)
    capture.add_argument("--repeats", type=int, default=config.DEFAULT_REPEATS)
    capture.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    capture.add_argument("--timeout-s", type=float, default=config.DEFAULT_TIMEOUT_S)
    capture.add_argument("--fixture-version", type=int, default=config.FIXTURE_VERSION)
    capture.add_argument(
        "--rubric",
        type=Path,
        default=None,
        help="Rubric file the sweep will be scored with; its hash is part of "
        "the plan hash (default: bench/fixtures/rubric.json).",
    )
    capture.add_argument(
        "--judge-model",
        default=None,
        help="Judge model id the sweep will be scored with; recorded in "
        "meta.json and covered by the plan hash.",
    )
    capture.add_argument("--keep-raw", action="store_true")
    capture.add_argument(
        "--force",
        action="store_true",
        help="Replace the sweep. Records captured under a different plan hash "
        "are archived to records.<plan_hash>.jsonl.bak, never mixed into the "
        "new records.jsonl.",
    )
    capture.add_argument("--dry-run", action="store_true")
    capture.add_argument("--no-retry-failures", action="store_true")
    capture.add_argument("--quiet", action="store_true")
    capture.set_defaults(func=_command_capture)

    score = subparsers.add_parser(
        "score",
        help="Score a sweep's records.jsonl into scores.jsonl, offline.",
    )
    score.add_argument("sweep_dir", nargs="?", type=Path, default=None)
    score.add_argument("--sweep", default=None)
    score.add_argument("--root", type=Path, default=config.DATA_ROOT)
    score.add_argument("--rubric", type=Path, default=None)
    score.add_argument("--output", type=Path, default=None)
    score.add_argument(
        "--allow-stale",
        action="store_true",
        help="Score even though the rubric/plan/judge differs from the sweep "
        "metadata. The report will carry a staleness banner.",
    )
    score.add_argument(
        "--judge-repeats",
        type=int,
        default=None,
        help="Judge only this repeat index (default: every repeat). "
        "Unjudged cells are recorded as judge_missing, never imputed.",
    )
    score.add_argument(
        "--judge-scenarios",
        default=None,
        help="Comma-separated scenarios to judge (default: all). Other "
        "scenarios are recorded as judge_missing, never imputed.",
    )
    score.add_argument(
        "--judge",
        default=None,
        help="Judge model id. Enables the blind LLM judge (rubric §8).",
    )
    score.add_argument(
        "--judge-base-url",
        default=None,
        help="OpenAI-compatible base URL (or full /chat/completions URL).",
    )
    score.add_argument(
        "--judge-model",
        default=None,
        help="Provider model id, when it differs from --judge.",
    )
    score.add_argument(
        "--judge-key-env",
        default=None,
        help="Environment variable holding the judge API key.",
    )
    score.add_argument(
        "--judge-timeout-s",
        type=float,
        default=config.JUDGE_DEFAULT_TIMEOUT_S,
    )
    score.add_argument("--quiet", action="store_true")
    score.set_defaults(func=_command_score)

    report = subparsers.add_parser(
        "report",
        help="Render report.md and report.json from a scored sweep.",
    )
    report.add_argument("sweep_dir", nargs="?", type=Path, default=None)
    report.add_argument("--sweep", default=None)
    report.add_argument("--root", type=Path, default=config.DATA_ROOT)
    report.add_argument("--rubric", type=Path, default=None)
    report.add_argument(
        "--allow-stale",
        action="store_true",
        help="Render even when scores.jsonl was produced under a different "
        "rubric or plan hash. The report starts with a staleness banner.",
    )
    report.add_argument("--quiet", action="store_true")
    report.set_defaults(func=_command_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
