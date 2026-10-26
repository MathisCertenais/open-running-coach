"""Render ``report.md`` and ``report.json`` from stored sweep data.

The report exists to stop a reader from reading the Composite first. It renders
the blocker rate before any quality number, takes every verdict from
``aggregate()`` and never crowns a model on a composite delta, and states the
cohort of every model before it says anything comparative (spec §8, rubric §9,
§11).

It is deterministic on purpose: the only inputs are ``meta.json``,
``records.jsonl``, ``scores.jsonl`` and the current roster. No wall clock and no
network call enter the output, so the same inputs produce byte-identical
``report.md``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from . import config
from .plan import sha256_payload
from .scoring.aggregate import aggregate
from .scoring.judge import judge_weights
from .scoring.rubric import Rubric, load_rubric

SCHEMA_VERSION = 1

MANDATORY_PARAGRAPH = (
    "A benchmark win means **best on these five prompts and these three "
    "scenarios**. It does not mean best coach. The benchmark measures whether "
    "an answer obeys the product's stated rules, stays grounded in the athlete's "
    "data, and avoids the specific claims the literature rules out. It does not "
    "measure whether the advice works: no injury outcomes, no adherence, no "
    "long-term performance, no real athlete feedback. A model that wins by a "
    "wide margin on scenario A and ties on B has not been shown to be safer; "
    "read the blocker column first."
)

DOES_NOT_MEASURE = (
    "It cannot conclude that one model is a better coach: only that it produced "
    "more rule-conformant answers to five fixed prompts on three synthetic "
    "athletes.",
    "It does not measure injury outcomes, adherence, long-term performance "
    "change, or whether the athlete followed the advice.",
    "It does not measure real athlete preference, trust, or comprehension.",
    "It does not measure safety in real use: the safety checks are static, and "
    "catch escalation language rather than whether a real injured athlete was "
    "helped.",
    "It does not measure factual correctness against a ground truth of "
    "coaching, because no such ground truth exists.",
    "It does not generalise to other athletes, other prompts, longer "
    "conversations, or multimodal input.",
    "It says nothing about cost, latency, context limits, or tool-calling "
    "reliability; measure those separately.",
    "A win on scenario A says nothing about scenario B; safety and helpfulness "
    "are different axes and a blocker is never averaged away.",
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _roster_flags() -> dict[str, dict]:
    """Current roster state, so a disabled model is reported as such.

    The pilot's ``meta.json`` recorded ``opencode-deepseek`` as available when
    it was captured. The roster is the authority on whether it may be scored
    now: a transport that injects its own agent context cannot measure the model,
    so the row is listed as disabled rather than quietly counted.
    """
    try:
        from .roster import load_roster

        roster = load_roster()
    except (OSError, ValueError):
        return {}
    return {
        spec.key: {
            "enabled": spec.enabled,
            "disabled_reason": spec.disabled_reason,
            "cohort": spec.cohort,
            "fidelity": spec.cohort,
        }
        for spec in roster.specs
    }


def _prompt_set_sha256(plan: Mapping[str, object]) -> str:
    prompts = plan.get("prompts") or []
    if prompts:
        return sha256_payload(prompts)
    return sha256_payload([])


def _planned_per_model(plan: Mapping[str, object]) -> int:
    prompts = len(plan.get("prompts") or [])
    fixtures = len(plan.get("fixtures") or [])
    repeats = int(plan.get("repeats") or 0)
    return max(0, prompts * fixtures * repeats)


def _capture_date(meta: Mapping[str, object]) -> date | None:
    for key in ("completed_at", "generated_at"):
        value = meta.get(key)
        if isinstance(value, str) and len(value) >= 10:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _fixture_age_days(
    meta: Mapping[str, object], plan: Mapping[str, object]
) -> list[dict]:
    capture = _capture_date(meta)
    rows: list[dict] = []
    if capture is None:
        return rows
    try:
        from .fixtures import load_fixture

        for fixture in plan.get("fixtures") or []:
            scenario = str(fixture.get("scenario") or "")
            version = int(fixture.get("version") or config.FIXTURE_VERSION)
            loaded = load_fixture(scenario, version)
            as_of = date.fromisoformat(str(loaded.as_of)[:10])
            rows.append(
                {
                    "scenario": scenario,
                    "version": version,
                    "as_of": as_of.isoformat(),
                    "age_days": max(0, (capture - as_of).days),
                }
            )
    except (OSError, ValueError):
        return rows
    return rows


def _model_records(
    records: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    by_model: dict[str, list[Mapping[str, object]]] = {}
    for record in records:
        key = str((record.get("model") or {}).get("key") or "")
        if key:
            by_model.setdefault(key, []).append(record)
    return by_model


def _cost_and_latency(rows: Sequence[Mapping[str, object]]) -> dict:
    costs = [
        float(row["cost_usd"])
        for row in rows
        if isinstance(row.get("cost_usd"), (int, float))
    ]
    latency_by_kind: dict[str, list[float]] = {}
    for row in rows:
        kind = str(row.get("latency_kind") or "unknown")
        value = row.get("latency_ms")
        if isinstance(value, (int, float)):
            latency_by_kind.setdefault(kind, []).append(float(value))
    return {
        "cost_usd": round(sum(costs), 6) if costs else None,
        "cost_reported": bool(costs),
        "latency_ms": {
            kind: round(sum(values) / len(values), 1)
            for kind, values in sorted(latency_by_kind.items())
        },
        "usage_reported": any(row.get("usage") for row in rows),
    }


# ---------------------------------------------------------------------------
# Rule detail and cells
# ---------------------------------------------------------------------------


def _rule_detail(
    scores: Sequence[Mapping[str, object]],
    rubric: Rubric,
    disabled: set[str],
) -> list[dict]:
    by_model: dict[str, list[Mapping[str, object]]] = {}
    for entry in scores:
        key = str((entry.get("model") or {}).get("key") or "")
        if key and key not in disabled:
            by_model.setdefault(key, []).append(entry)

    detail: list[dict] = []
    for rule in rubric.rules:
        models: list[dict] = []
        for key in sorted(by_model):
            applicable = 0
            passed = 0
            skipped = 0
            evidence = ""
            evidence_detail = ""
            for entry in sorted(
                by_model[key], key=lambda row: str(row.get("record_id") or "")
            ):
                for outcome in entry.get("outcomes") or []:
                    if outcome.get("rule_id") != rule.id:
                        continue
                    if not outcome.get("applies"):
                        skipped += 1
                        continue
                    applicable += 1
                    if outcome.get("passed"):
                        passed += 1
                    elif not evidence:
                        evidence = str(outcome.get("evidence") or "")
                        evidence_detail = str(outcome.get("detail") or "")
            if applicable == 0 and skipped == 0:
                continue
            models.append(
                {
                    "model": key,
                    "applicable": applicable,
                    "passed": passed,
                    "failed": applicable - passed,
                    "skipped": skipped,
                    "pass_rate": (
                        round(passed / applicable, 6) if applicable else None
                    ),
                    "evidence": evidence,
                    "evidence_detail": evidence_detail,
                }
            )
        detail.append(
            {
                "rule_id": rule.id,
                "severity": rule.severity.value,
                "models": models,
            }
        )
    return detail


def _blocker_grids(
    scores: Sequence[Mapping[str, object]],
    disabled: set[str],
    repeats: int,
) -> dict[str, dict]:
    """Per model, the scenario x prompt x repeat blocker grid.

    Repeats are the same prompt re-asked, not independent samples, so the grid
    is the honest unit: a cell blocked in every repeat is reproducible, one
    blocked in a single repeat is flaky. Reads scores only, never records.
    """
    grids: dict[str, dict] = {}
    for entry in scores:
        if not entry.get("scored"):
            continue
        key = str((entry.get("model") or {}).get("key") or "")
        if not key or key in disabled:
            continue
        scenario = str((entry.get("fixture") or {}).get("scenario") or "")
        prompt = str((entry.get("prompt") or {}).get("id") or "")
        repeat = int(entry.get("repeat") or 0)
        blocked = int((entry.get("counts") or {}).get("blocker") or 0) > 0
        if not scenario or not prompt or repeat < 0 or repeat >= repeats:
            continue
        grid = grids.setdefault(
            key, {"grid": {}, "blocked_answers": 0, "total": 0, "prompts": set()}
        )
        row = (
            grid["grid"].setdefault(scenario, {}).setdefault(prompt, [False] * repeats)
        )
        row[repeat] = row[repeat] or blocked
        grid["prompts"].add(prompt)

    result: dict[str, dict] = {}
    for key, grid in grids.items():
        rows = grid["grid"]
        blocked_answers = sum(
            1
            for scenarios in rows.values()
            for values in scenarios.values()
            for v in values
            if v
        )
        total = sum(
            len(values) for scenarios in rows.values() for values in scenarios.values()
        )
        prompts = sorted(grid["prompts"])
        all_repeats = 0
        for prompt in prompts:
            per_repeat = [
                any(
                    scenarios.get(prompt, [False] * repeats)[repeat]
                    for scenarios in rows.values()
                )
                for repeat in range(repeats)
            ]
            if all(per_repeat):
                all_repeats += 1
        result[key] = {
            "grid": {
                scenario: {
                    prompt: list(values) for prompt, values in sorted(prompts.items())
                }
                for scenario, prompts in sorted(rows.items())
            },
            "blocked_answers": blocked_answers,
            "total": total,
            "blocked_prompts_all_repeats": all_repeats,
            "prompts_total": len(prompts),
        }
    return result


def _cells(scores: Sequence[Mapping[str, object]], disabled: set[str]) -> list[dict]:
    cells: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    for entry in scores:
        if not entry.get("scored"):
            continue
        key = str((entry.get("model") or {}).get("key") or "")
        if not key or key in disabled:
            continue
        cell = (
            key,
            str((entry.get("fixture") or {}).get("scenario") or ""),
            str((entry.get("prompt") or {}).get("id") or ""),
        )
        cells.setdefault(cell, []).append(entry)

    def median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    rows: list[dict] = []
    for (model, scenario, prompt), entries in sorted(cells.items()):
        gates = [1.0 if entry.get("gate") == "pass" else 0.0 for entry in entries]
        composites = [
            float(entry["composite"])
            for entry in entries
            if isinstance(entry.get("composite"), (int, float))
        ]
        judges = [
            float(entry["judge"])
            for entry in entries
            if isinstance(entry.get("judge"), (int, float))
        ]
        rows.append(
            {
                "model": model,
                "scenario": scenario,
                "prompt": prompt,
                "repeats": len(entries),
                "gate": "pass" if (median(gates) or 0) >= 0.5 else "fail",
                "r": median(
                    [
                        float(entry["r"])
                        for entry in entries
                        if isinstance(entry.get("r"), (int, float))
                    ]
                ),
                "coverage": median(
                    [
                        float(entry["coverage"])
                        for entry in entries
                        if isinstance(entry.get("coverage"), (int, float))
                    ]
                ),
                "composite": median(composites) if composites else None,
                "judge": median(judges) if judges else None,
                # Never imputed: a repeat the judge did not score is counted
                # here, not filled with the cell median or a neighbour.
                "judge_missing": len(entries) - len(judges),
            }
        )
    return rows


def _failures(records: Sequence[Mapping[str, object]]) -> list[dict]:
    rows: list[dict] = []
    for record in sorted(records, key=lambda row: str(row.get("record_id") or "")):
        if record.get("status") == "ok":
            continue
        error = record.get("error") or {}
        rows.append(
            {
                "record_id": record.get("record_id"),
                "model": (record.get("model") or {}).get("key"),
                "scenario": (record.get("fixture") or {}).get("scenario"),
                "prompt": (record.get("prompt") or {}).get("id"),
                "repeat": record.get("repeat"),
                "status": record.get("status"),
                "kind": error.get("kind") if isinstance(error, Mapping) else None,
                "message": error.get("message") if isinstance(error, Mapping) else None,
                "latency_ms": record.get("latency_ms"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Limitations generated from data
# ---------------------------------------------------------------------------


def _limitations(
    meta: Mapping[str, object],
    plan: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
    scores: Sequence[Mapping[str, object]],
    models: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
    judge_present: bool,
    disabled: set[str],
    rubric: Rubric,
) -> list[str]:
    notes: list[str] = []
    answers = [
        record
        for record in records
        if record.get("status") == "ok" and record.get("answer")
    ]
    production = sum(
        1
        for record in answers
        if (record.get("model") or {}).get("fidelity") == "production"
    )
    proxy = sum(
        1
        for record in answers
        if (record.get("model") or {}).get("fidelity") == "proxy"
    )
    if proxy:
        notes.append(
            f"Fidelity mix: {production} production answers and {proxy} proxy "
            "answers. Proxy answers were produced under a wrapper and are not "
            "comparable with the production cohort."
        )
    else:
        notes.append(
            f"Fidelity mix: {production} production answers, 0 proxy answers. "
            "Every answer went through the production path."
        )

    for model in models:
        if model.get("key") in disabled:
            continue
        notes.append(
            f"{model['key']}: {model.get('answers')} scorable answers across "
            f"{model.get('cells')} cells ({model.get('attempted')} attempted). "
            "The statistical n is the cell count, not the answer count."
        )

    ages = _fixture_age_days(meta, plan)
    if ages:
        for row in ages:
            notes.append(
                f"Fixture {row['scenario']}.v{row['version']} is anchored to "
                f"{row['as_of']}, {row['age_days']} day(s) before capture."
            )
    else:
        notes.append("Fixture age could not be derived from the stored metadata.")

    truncated = sum(
        1 for record in records if (record.get("context") or {}).get("truncated")
    )
    notes.append(
        f"Truncated contexts: {truncated} of {len(records)} records. A fact that "
        "never reached the model is skipped by the relevant rule, not failed."
    )

    if not judge_present:
        notes.append(
            "No judge value is available (the judge was not run, or every judged "
            "cell was invalid/unstable): J is absent, the composite excludes its "
            "0.30 term (marked composite_partial), and §9.2 condition 2 cannot "
            "be checked."
        )

    silent = [
        str(model.get("key"))
        for model in models
        if model.get("key") not in disabled and not model.get("usage_reported")
    ]
    if silent:
        notes.append(
            "Token usage not reported by: "
            + ", ".join(sorted(silent))
            + '. The table prints "not reported" rather than a zero.'
        )

    if failures:
        notes.append(
            f"Failed captures: {len(failures)}. They are missing cells, not zero "
            "scores."
        )

    gaps = sorted(
        {
            str(outcome.get("rule_id"))
            for entry in scores
            for outcome in entry.get("outcomes") or []
            if outcome.get("skipped_reason") == "payload_gap"
        }
    )
    if gaps:
        notes.append(
            "Payload gaps (product defects, not model failures): "
            + ", ".join(gaps)
            + " were skipped because the frozen snapshot does not expose the "
            "field the rule needs. They start scoring on a v2 fixture that "
            "carries it (rubric §12.1)."
        )

    gaps_in_recall = [str(rule) for rule in (rubric.recall or {}).get("rules") or []]
    if gaps_in_recall:
        counts: list[str] = []
        for rule_id in gaps_in_recall:
            applicable = failed = 0
            for entry in scores:
                if not entry.get("scored"):
                    continue
                if str((entry.get("model") or {}).get("key") or "") in disabled:
                    continue
                for outcome in entry.get("outcomes") or []:
                    if outcome.get("rule_id") != rule_id or not outcome.get("applies"):
                        continue
                    applicable += 1
                    if not outcome.get("passed"):
                        failed += 1
            counts.append(f"{rule_id} {failed} failed of {applicable} applicable")
        source = str((rubric.recall or {}).get("source") or rubric.source)
        recorded = (rubric.recall or {}).get("recorded_false_negatives")
        recorded_text = (
            f"{recorded} answers that should have been blockers and passed"
            if recorded is not None
            else "false negatives"
        )
        notes.append(
            f"Blocker recall is an undercount, not a proof of safety: {source} "
            f"records {recorded_text} on the {', '.join(gaps_in_recall)} checks. "
            "This sweep: " + "; ".join(counts) + ". A 0-blocker row means the "
            "checks found nothing, not that there was nothing to find."
        )

    invalid_judge = [
        str((entry.get("judge_meta") or {}).get("detail") or "")
        for entry in scores
        if entry.get("judge_status") == "judge-invalid"
    ]
    if invalid_judge:
        no_raw = sum(
            1 for detail in invalid_judge if "full results were not retained" in detail
        )
        notes.append(
            f"Judge invalid: {len(invalid_judge)} judged cell(s) produced no "
            f"score and are excluded, never imputed. {no_raw} had tool calls "
            "whose full results were not retained (a capture without "
            "--keep-raw); the rest failed the reply contract after its retry."
        )
    missing_judge = sum(
        int(model.get("judge_missing") or 0)
        for model in models
        if model.get("key") not in disabled
    )
    if missing_judge:
        notes.append(
            f"Judge coverage: {missing_judge} scorable answer(s) have no judge "
            "score (judge_missing). They are counted and excluded, never "
            "imputed, so mean J is computed over the judged PASS answers only."
        )
    return notes


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _judge_statement(
    meta: Mapping[str, object],
    rubric: Rubric,
    withheld: bool,
) -> dict | None:
    """The report's judge/gate disclosure, generated from the calibration run.

    The prose is the ruling's; the numbers (medians within +/-1, the miss) are
    read from ``meta.json`` so a different judge or run cannot reuse a claim it
    did not earn.
    """
    judge = meta.get("judge") if isinstance(meta.get("judge"), Mapping) else {}
    if not judge:
        return None
    calibration = (
        judge.get("calibration")
        if isinstance(judge.get("calibration"), Mapping)
        else {}
    )
    model = str(judge.get("model") or meta.get("judge_model") or "not run")
    prompt_sha = str(judge.get("prompt_sha256") or "")
    max_tokens = int(judge.get("max_tokens") or config.JUDGE_MAX_TOKENS)
    gate = str(judge.get("gate") or config.JUDGE_GATE)
    weights = judge_weights(rubric.judge)

    pairs: list[dict] = []
    for answer in calibration.get("answers") or []:
        if not isinstance(answer, Mapping):
            continue
        for dimension, row in (answer.get("per_dimension") or {}).items():
            if not isinstance(row, Mapping) or row.get("error") is None:
                continue
            pairs.append(
                {
                    "answer": str(answer.get("id") or ""),
                    "dimension": str(dimension),
                    "hand": row.get("hand"),
                    "median": row.get("median"),
                    "calls": list(row.get("calls") or []),
                    "error": float(row["error"]),
                    "weight": float(weights.get(str(dimension), 0.0)),
                }
            )
    within = sum(1 for pair in pairs if abs(pair["error"]) <= 1)
    total = len(pairs)
    misses = [pair for pair in pairs if abs(pair["error"]) > 1]
    if len(misses) == 1:
        miss = misses[0]
        where = (
            "the non-answer" if miss["answer"].startswith("cal-01") else miss["answer"]
        )
        miss_text = (
            f"the single miss is {str(miss['dimension']).title()} on {where} "
            f"(hand {miss['hand']:g}, median {miss['median']:g}, calls "
            f"{'/'.join(str(call) for call in miss['calls'])}), worth "
            f"{abs(miss['error']) * miss['weight']:.2f} of J"
        )
    elif not misses:
        miss_text = "no median missed"
    else:
        miss_text = "the misses are " + "; ".join(
            f"{miss['answer']} {miss['dimension']} (hand {miss['hand']:g}, "
            f"median {miss['median']:g}, e={miss['error']:+g})"
            for miss in misses
        )

    sentence = (
        f"Judge. {model}, temperature 0, max_tokens {max_tokens}, prompt "
        f"sha256 {prompt_sha}, no tools, identity and deterministic outcomes "
        f"hidden. Gate {gate}, a documented relaxation of §8.5 written after "
        f"these calibration results were known. Calibration: {within} of "
        f"{total} medians within ±1; {miss_text}. Across all four candidates "
        "every score error was lenient and none was harsh: J is an upper bound "
        "on quality, not a neutral estimate."
    )
    composite = (
        "No composite is published this sweep (d(Composite)/dJ = 0.075, so a "
        "0.25 J error moves it ~1.9 points out of 100). Read the blocker "
        "column first."
    )
    return {
        "sentence": sentence,
        "composite_note": composite,
        "within_one": within,
        "total_pairs": total,
        "misses": misses,
        "withheld": withheld,
    }


def _stale_fields(
    plan: Mapping[str, object],
    scores: Sequence[Mapping[str, object]],
    rubric: Rubric,
) -> dict[str, dict]:
    """Where ``scores.jsonl`` disagrees with the current header.

    Empty means the scores were produced under the rubric and plan the report
    is about to print. A non-empty result is not a warning: it means the numbers
    and the header describe different measurements.
    """
    stale: dict[str, dict] = {}
    rubric_hashes = sorted(
        {
            str(entry.get("rubric_sha256"))
            for entry in scores
            if entry.get("rubric_sha256")
        }
    )
    if any(value != rubric.sha256 for value in rubric_hashes):
        stale["rubric_sha256"] = {
            "recorded": rubric_hashes,
            "current": rubric.sha256,
            "current_version": rubric.version,
        }
    recorded_rubric = plan.get("rubric_hash")
    if recorded_rubric and recorded_rubric != rubric.sha256:
        stale["plan_rubric_hash"] = {
            "recorded": [str(recorded_rubric)],
            "current": rubric.sha256,
            "current_version": rubric.version,
        }
    expected_plan = plan.get("plan_hash")
    plan_hashes = sorted(
        {str(entry.get("plan_hash")) for entry in scores if entry.get("plan_hash")}
    )
    if expected_plan and any(value != str(expected_plan) for value in plan_hashes):
        stale["plan_hash"] = {
            "recorded": plan_hashes,
            "current": str(expected_plan),
        }
    return stale


def build_report(
    sweep_dir: Path, rubric: Rubric | None = None, *, allow_stale: bool = False
) -> dict:
    """Read one sweep directory and return the report as data.

    ``scores.jsonl`` is refused when it was produced under a rubric or plan
    hash other than the header's: printing it would attribute old numbers to
    the current rubric. ``allow_stale`` is the explicit opt-in that keeps the
    report possible for an audit, and it stamps a banner on the output.
    """
    rubric = rubric or load_rubric()
    meta = _read_json(sweep_dir / config.META_FILENAME, {})
    if not isinstance(meta, Mapping):
        meta = {}
    plan = meta.get("plan") if isinstance(meta.get("plan"), Mapping) else {}
    records = _read_jsonl(sweep_dir / config.RECORDS_FILENAME)
    scores = _read_jsonl(sweep_dir / config.SCORES_FILENAME)
    if not scores:
        raise ValueError(
            f"{sweep_dir} has no {config.SCORES_FILENAME}; run `score` first"
        )
    stale = _stale_fields(plan, scores, rubric)
    if stale and not allow_stale:
        detail = "; ".join(
            f"{field} recorded={value['recorded']} current={value['current']}"
            for field, value in sorted(stale.items())
        )
        raise ValueError(
            f"refusing to report stale scores in {sweep_dir}: {detail}. "
            "Re-run `score` under the current rubric/plan, or pass "
            "--allow-stale to render them with a staleness banner."
        )

    flags = _roster_flags()
    disabled = {key for key, value in flags.items() if value.get("enabled") is False}

    judge_model = meta.get("judge_model")
    meta_judge = meta.get("judge") if isinstance(meta.get("judge"), Mapping) else {}
    judge_prompt_sha256 = meta_judge.get("prompt_sha256")
    first_entry = next((entry for entry in scores if entry.get("judge_meta")), None)
    if isinstance(first_entry, Mapping):
        judge_meta = first_entry.get("judge_meta") or {}
        judge_model = judge_model or judge_meta.get("model")
        judge_prompt_sha256 = judge_prompt_sha256 or judge_meta.get("prompt_sha256")
    summary = aggregate(
        scores,
        rubric,
        judge_model=str(judge_model) if judge_model else None,
        judge_prompt_sha256=str(judge_prompt_sha256) if judge_prompt_sha256 else None,
    )

    records_by_model = _model_records(records)
    planned = _planned_per_model(plan)
    models: list[dict] = []
    repeats = int(plan.get("repeats") or 0) or max(
        (int(entry.get("repeat") or 0) + 1 for entry in scores), default=1
    )
    grids = _blocker_grids(scores, disabled, repeats)
    for model in summary["models"]:
        key = str(model["key"])
        rows = records_by_model.get(key, [])
        extra = _cost_and_latency(rows)
        flag = flags.get(key, {})
        is_disabled = flag.get("enabled") is False
        grid = grids.get(key)
        models.append(
            {
                **model,
                "planned": planned or len(rows),
                "ok": sum(1 for row in rows if row.get("status") == "ok"),
                "disabled": is_disabled,
                "disabled_reason": flag.get("disabled_reason") if is_disabled else None,
                "blocker_grid": grid["grid"] if grid else None,
                "blocked_answers": grid["blocked_answers"] if grid else 0,
                "blocked_answers_total": grid["total"] if grid else 0,
                "blocked_prompts_all_repeats": (
                    grid["blocked_prompts_all_repeats"] if grid else 0
                ),
                "prompts_total": grid["prompts_total"] if grid else 0,
                **extra,
            }
        )

    verdicts = [
        verdict
        for verdict in summary["verdicts"]
        if verdict.get("left") not in disabled and verdict.get("right") not in disabled
    ]
    insufficient = [
        {
            "model": model["key"],
            "cohort": model["cohort"],
            "reasons": list(model.get("reasons") or []),
        }
        for model in models
        if model.get("insufficient_evidence") and not model.get("disabled")
    ]

    failures = _failures(records)
    judge_present = bool(summary["judge"].get("present")) or bool(meta_judge)
    judge_withheld = bool(summary["judge"].get("withheld"))
    judge_unstable_rate = summary["judge"].get("unstable_rate")
    judge_gate = str(summary["judge"].get("gate") or config.JUDGE_GATE)
    header = {
        "sweep": meta.get("sweep") or sweep_dir.name,
        "plan_hash": plan.get("plan_hash"),
        "date": meta.get("completed_at") or meta.get("generated_at"),
        "git_sha": meta.get("git_sha"),
        "fixtures": list(plan.get("fixtures") or []),
        "prompt_set_sha256": _prompt_set_sha256(plan),
        "system_prompt_sha256": (meta.get("system_prompt") or {}).get("sha256")
        if isinstance(meta.get("system_prompt"), Mapping)
        else None,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "judge_model": judge_model,
        "judge_prompt_sha256": judge_prompt_sha256,
        "judge_gate": judge_gate,
        "judge_unstable_rate": judge_unstable_rate,
        "judge_withheld": judge_withheld,
        "prices_as_of": meta.get("prices_as_of"),
        "cohorts": dict(summary["cohorts"]),
        "repeats": plan.get("repeats"),
    }

    limitations = _limitations(
        meta,
        plan,
        records,
        scores,
        models,
        failures,
        judge_present,
        disabled,
        rubric,
    )
    if judge_withheld:
        limitations.append(
            "Judge withheld: the §8.4 unstable-cell rate on the scored set is "
            f"{100.0 * float(judge_unstable_rate or 0.0):.1f}%, above the 15% "
            "provisional-certification cap. J is not published and no verdict "
            "is issued (rubric §12.7)."
        )
    if judge_model:
        vendor = str(judge_model).split("/", 1)[0].lower()
        origins = {
            str((record.get("model") or {}).get("origin") or "").lower()
            for record in records
        }
        if vendor and vendor in origins:
            limitations.append(
                f"Judge vendor disclosure: the judge ({judge_model}) shares a "
                f"vendor with at least one model under test ({vendor}). Rubric "
                "§8.1 requires the disclosure; the judge is not the same model."
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "sweep": header["sweep"],
        "judge_present": judge_present,
        "judge_withheld": judge_withheld,
        "judge_unstable_rate": judge_unstable_rate,
        "judge_gate": judge_gate,
        "judge_statement": _judge_statement(meta, rubric, judge_withheld),
        "stale": stale,
        "header": header,
        "blockers": [
            {
                "model": model["key"],
                "cohort": model["cohort"],
                "fidelity": model["fidelity"],
                "answers": model["answers"],
                "blockers": model["blockers"],
                "rate": model["blocker_rate"],
                "wilson": model["blocker_wilson"],
                "disabled": model["disabled"],
            }
            for model in models
        ],
        "verdicts": verdicts,
        "insufficient_evidence": insufficient,
        "models": models,
        "cells": _cells(scores, disabled),
        "rules": _rule_detail(scores, rubric, disabled),
        "failures": failures,
        "limitations": limitations,
        "mandatory_paragraph": MANDATORY_PARAGRAPH,
        "does_not_measure": list(DOES_NOT_MEASURE),
        "reproduction": {
            "plan_hash": plan.get("plan_hash"),
            "scores_recomputable": True,
            "commands": [
                f"python -m bench.cli score {sweep_dir}",
                f"python -m bench.cli report {sweep_dir}",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _cell(value: object, empty: str = "—") -> str:
    if value is None or value == "":
        return empty
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _pct(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{100.0 * float(value):.1f}%"


def _interval(value: object) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return "—"
    return f"{100.0 * float(value[0]):.1f}–{100.0 * float(value[1]):.1f}%"


def _verdict_lines(
    verdict: Mapping[str, object], *, judge_withheld: bool = False
) -> list[str]:
    conditions = verdict.get("conditions") or {}
    lines: list[str] = []
    status = str(verdict.get("status"))
    left = str(verdict.get("left"))
    right = str(verdict.get("right"))
    if status == "better":
        lines.append(f"**{left} is better than {right} on this benchmark.**")
        lines.append("")
        lines.append("All four §9.2 conditions hold:")
    elif status == "insufficient_evidence":
        lines.append(
            f"**{left} vs {right}: insufficient evidence.** No verdict is issued."
        )
        lines.append("")
        lines.append(
            "Reason: "
            + ", ".join(str(reason) for reason in verdict.get("reasons") or [])
        )
    else:
        lines.append(
            f"**No distinguishable difference between {left} and {right} on this "
            "benchmark.**"
        )
        lines.append("")
        lines.append(
            "A composite gap is not a finding. Failing conditions: "
            + ", ".join(str(reason) for reason in verdict.get("reasons") or [])
        )
    blocker = conditions.get("blocker_rate") or {}
    lines.append(
        f"1. Blocker rate: {left} {_pct(blocker.get('left'))} "
        f"[{_interval(blocker.get('left_interval'))}] vs {right} "
        f"{_pct(blocker.get('right'))} "
        f"[{_interval(blocker.get('right_interval'))}] — "
        f"{'pass' if blocker.get('passed') else 'fail'} ({blocker.get('detail')})."
    )
    dominance = conditions.get("dominance") or {}
    legs = dominance.get("legs") or {}
    left_judge = (
        "withheld"
        if judge_withheld
        else _cell((legs.get("judge_mean") or [None, None])[0])
    )
    right_judge = (
        "withheld"
        if judge_withheld
        else _cell((legs.get("judge_mean") or [None, None])[1])
    )
    lines.append(
        "2. Dominance: "
        f"median R {_cell((legs.get('r_median') or [None, None])[0])} vs "
        f"{_cell((legs.get('r_median') or [None, None])[1])}; "
        f"mean Coverage {_cell((legs.get('coverage_mean') or [None, None])[0])} vs "
        f"{_cell((legs.get('coverage_mean') or [None, None])[1])}; "
        f"mean J {left_judge} vs {right_judge} — "
        f"{'pass' if dominance.get('passed') else 'fail'} "
        f"({dominance.get('detail')})."
    )
    sign = conditions.get("sign_test") or {}
    lines.append(
        f"3. Paired sign test: {sign.get('wins')} wins, {sign.get('losses')} "
        f"losses, {sign.get('ties')} ties over {sign.get('cells')} cells "
        f"(needed {sign.get('needed')}, p = {_cell(sign.get('p_two_sided'))}) — "
        f"{'pass' if sign.get('passed') else 'fail'}."
    )
    instability = conditions.get("instability") or {}
    lines.append(
        f"4. Judge instability: {instability.get('unstable_cells')} excluded "
        f"cell(s) — {'pass' if instability.get('passed') else 'fail'}."
    )
    return lines


def render_markdown(report: Mapping[str, object]) -> str:
    """Render the report in spec §8's order."""
    header = report["header"]
    lines: list[str] = []
    lines.append(f"# AI coach benchmark — {report['sweep']}")
    lines.append("")
    if report.get("stale"):
        lines.append(
            "> **STALE SCORES — DO NOT QUOTE.** `scores.jsonl` was produced under "
            "a different rubric or plan hash than this header names "
            f"({', '.join(sorted(report['stale']))}). The numbers and the header "
            "describe different measurements: any verdict below is not "
            "comparable with a fresh score. Re-run `python -m bench.cli score` "
            "before using this report."
        )
        lines.append("")
    lines.append(
        "Generated offline from `records.jsonl` and `scores.jsonl`. No model was "
        "called to produce this report. The same inputs produce this file "
        "byte-for-byte."
    )
    lines.append("")
    lines.append("## 1. Header")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for label, value in (
        ("Sweep", header.get("sweep")),
        ("Plan hash", header.get("plan_hash")),
        ("Date", header.get("date")),
        ("Git sha", header.get("git_sha")),
        ("Prompt set sha256", header.get("prompt_set_sha256")),
        ("SYSTEM_PROMPT sha256", header.get("system_prompt_sha256")),
        ("Rubric version", header.get("rubric_version")),
        ("Rubric sha256", header.get("rubric_sha256")),
        ("Judge model", header.get("judge_model") or "not run"),
        ("Judge prompt sha256", header.get("judge_prompt_sha256") or "not run"),
        ("Prices as of", header.get("prices_as_of")),
        ("Repeats", header.get("repeats")),
    ):
        lines.append(f"| {label} | {_cell(value)} |")
    lines.append("")
    statement = report.get("judge_statement")
    if statement:
        lines.append("### Judge and gate")
        lines.append("")
        lines.append(str(statement.get("sentence") or ""))
        lines.append("")
        lines.append(str(statement.get("composite_note") or ""))
        lines.append("")
    if report.get("judge_withheld"):
        lines.append(
            "**J is withheld this sweep.** The §8.4 unstable-cell rate is "
            f"{_pct(report.get('judge_unstable_rate'))}, above the 15% "
            "provisional-certification cap, so no mean J and no verdict are "
            "published."
        )
        lines.append("")
    lines.append("Fixtures:")
    lines.append("")
    lines.append("| Scenario | Version | Snapshot sha256 | Tool context sha256 |")
    lines.append("| --- | --- | --- | --- |")
    for fixture in header.get("fixtures") or []:
        lines.append(
            f"| {fixture.get('scenario')} | {fixture.get('version')} | "
            f"`{fixture.get('snapshot_sha256')}` | "
            f"`{fixture.get('tool_context_sha256')}` |"
        )
    lines.append("")
    lines.append("Cohorts:")
    lines.append("")
    for cohort, members in sorted((header.get("cohorts") or {}).items()):
        lines.append(f"- **{cohort}**: {', '.join(members)}")
    lines.append("")
    lines.append(
        "Verdicts are computed **within a cohort**. A production and a proxy "
        "model are never compared in one verdict (spec §7.5)."
    )
    lines.append("")

    lines.append("## 2. Blocker rate (read this first)")
    lines.append("")
    lines.append(
        "Rubric §11: the first question a reader should be able to answer is "
        '"did it ever say something dangerous or invented?", not "which '
        'number is bigger?".'
    )
    lines.append("")
    lines.append(
        "| Model | Cohort | Fidelity | Answered | Blockers | Blocker rate | "
        "Wilson 95% |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in report["blockers"]:
        if row.get("disabled"):
            lines.append(
                f"| {row['model']} | {row['cohort']} | {row['fidelity']} | "
                "disabled — not scored | — | — | — |"
            )
            continue
        lines.append(
            f"| {row['model']} | {row['cohort']} | {row['fidelity']} | "
            f"{row['answers']} | {row['blockers']} | {_pct(row['rate'])} | "
            f"{_interval(row['wilson'])} |"
        )
    lines.append("")
    lines.append(
        "Any blocker rate above zero is the headline for that model. `R` excludes "
        "blocker answers by construction, which is why it is never the first "
        "column."
    )
    lines.append("")

    grid_models = [
        model
        for model in report["models"]
        if model.get("blocker_grid") and not model.get("disabled")
    ]
    lines.append("### Blocker grid")
    lines.append("")
    lines.append(
        "Read the grid, not the totals. Repeats re-ask the same prompt of the "
        "same model on the same fixture; the effective sample is five prompts "
        "per model, not fifteen answers."
    )
    lines.append("")
    repeats = int(header.get("repeats") or 0) or 1
    for model in grid_models:
        grid = model["blocker_grid"]
        lines.append(
            f"**{model['key']}** — blocked answers: "
            f"{model.get('blocked_answers')}/{model.get('blocked_answers_total')}; "
            f"blocked prompts: {model.get('blocked_prompts_all_repeats')}/"
            f"{model.get('prompts_total')} in every repeat"
        )
        lines.append("")
        lines.append(
            "| Scenario | Prompt | "
            + " | ".join(f"repeat {repeat}" for repeat in range(repeats))
            + " |"
        )
        lines.append(
            "| --- | --- | " + " | ".join("---" for _ in range(repeats)) + " |"
        )
        for scenario in sorted(grid):
            for prompt in sorted(grid[scenario]):
                values = list(grid[scenario][prompt])
                values += [False] * (repeats - len(values))
                cells = " | ".join("B" if value else "." for value in values[:repeats])
                lines.append(f"| {scenario} | {prompt} | {cells} |")
        lines.append("")
    if grid_models:
        blocked = sum(int(model.get("blocked_answers") or 0) for model in grid_models)
        total = sum(
            int(model.get("blocked_answers_total") or 0) for model in grid_models
        )
        prompt_hits = sum(
            int(model.get("blocked_prompts_all_repeats") or 0) for model in grid_models
        )
        lines.append(
            f"All models — blocked answers: {blocked}/{total}; prompts blocked "
            f"in every repeat: {prompt_hits} across {len(grid_models)} model(s)."
        )
        lines.append("")

    lines.append("## 3. Verdict")
    lines.append("")
    if report["insufficient_evidence"]:
        lines.append("### Insufficient evidence")
        lines.append("")
        for item in report["insufficient_evidence"]:
            lines.append(
                f"- **{item['model']}** ({item['cohort']}) — insufficient "
                f"evidence, not ranked. Reason: " + "; ".join(item.get("reasons") or [])
            )
        lines.append("")
    if not report["verdicts"]:
        lines.append(
            "No within-cohort pair is eligible for a §9.2 comparison in this "
            "sweep. No model is declared better than another."
        )
        lines.append("")
    for verdict in report["verdicts"]:
        lines.extend(
            _verdict_lines(verdict, judge_withheld=bool(report.get("judge_withheld")))
        )
        lines.append("")
    disabled_names = sorted(
        row["model"] for row in report["blockers"] if row.get("disabled")
    )
    if disabled_names:
        lines.append("### Disabled roster entries")
        lines.append("")
        for model in report["models"]:
            if not model.get("disabled"):
                continue
            lines.append(
                f"- **{model['key']}** ({model['cohort']}) — disabled, not "
                f"scored. {model.get('disabled_reason') or ''}".rstrip()
            )
        lines.append("")

    lines.append("## 4. Per-model metrics")
    lines.append("")
    lines.append(
        "Rubric §9.2 metrics. Composite is deliberately absent from this table: "
        "it is a reporting convenience, not the arbiter."
    )
    lines.append("")
    lines.append(
        "| Model | Cohort | Fidelity | Answered/Planned | Gate pass | "
        "Median R (PASS) | IQR | Mean Coverage | SD | Mean J (PASS) | SD | "
        "Instability | Invalid | Judge missing | Mean words | Truncation | "
        "Cost (USD) | Latency |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- | --- | --- | --- |"
    )
    for model in report["models"]:
        if model.get("disabled"):
            lines.append(
                f"| {model['key']} | {model['cohort']} | {model['fidelity']} | "
                "disabled — not scored | — | — | — | — | — | — | — | — | — | "
                "— | — | — | — | — |"
            )
            continue
        iqr = model.get("r_iqr") or [None, None]
        latency = model.get("latency_ms") or {}
        latency_text = ", ".join(
            f"{kind} {value:.0f} ms" for kind, value in sorted(latency.items())
        )
        cost = (
            f"{model['cost_usd']:.4f}" if model.get("cost_reported") else "not reported"
        )
        judge_present = bool(report.get("judge_present"))
        withheld = bool(report.get("judge_withheld"))
        judge_mean = (
            "withheld"
            if withheld
            else (_cell(model.get("judge_mean")) if judge_present else "—")
        )
        judge_sd = (
            "withheld"
            if withheld
            else (_cell(model.get("judge_sd")) if judge_present else "—")
        )
        lines.append(
            f"| {model['key']} | {model['cohort']} | {model['fidelity']} | "
            f"{model.get('answers')}/{model.get('planned')} | "
            f"{_pct(model.get('gate_pass_rate'))} | {_cell(model.get('r_median'))} | "
            f"{_cell(iqr[0])}–{_cell(iqr[1])} | {_cell(model.get('coverage_mean'))} | "
            f"{_cell(model.get('coverage_sd'))} | "
            f"{judge_mean} | {judge_sd} | "
            f"{_pct(model.get('judge_instability')) if judge_present else '—'} | "
            f"{model.get('judge_invalid') if judge_present else '—'} | "
            f"{model.get('judge_missing') if judge_present else '—'} | "
            f"{_cell(model.get('words_mean'))} | "
            f"{_pct(model.get('truncation_rate'))} | {cost} | {latency_text or '—'} |"
        )
    lines.append("")

    repeats = header.get("repeats") or 1
    lines.append(f"## 5. Per-cell results (descriptive, n = {repeats})")
    lines.append("")
    lines.append(
        "Per-cell rows are descriptive only and are never used to rank (rubric "
        "§9.3). Composite is not published this sweep: d(Composite)/dJ = 0.075, "
        "so a 0.25 J error moves it ~1.9 points out of 100."
    )
    if not report.get("judge_present"):
        lines.append("")
        lines.append("No judge was run, so no composite is defined for these cells.")
    lines.append("")
    lines.append("| Model | Scenario | Prompt | Gate | R | Coverage | Judge |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    withheld = bool(report.get("judge_withheld"))
    for cell in report["cells"]:
        if withheld:
            judge = "withheld"
        elif cell.get("judge_missing") == 0:
            judge = _cell(cell.get("judge"))
        else:
            judge = f"missing ({cell.get('judge_missing')})"
        lines.append(
            f"| {cell['model']} | {cell['scenario']} | {cell['prompt']} | "
            f"{cell['gate']} | {_cell(cell.get('r'))} | "
            f"{_cell(cell.get('coverage'))} | {judge} |"
        )
    if not report["cells"]:
        lines.append("| — | — | — | — | — | — | — |")
    lines.append("")

    lines.append("## 6. Per-rule detail")
    lines.append("")
    lines.append(
        "One failing answer span per rule so the number can be audited without "
        "re-running the scorer. Skips are shown, not counted as passes."
    )
    lines.append("")
    for rule in report["rules"]:
        models = rule.get("models") or []
        if not models:
            continue
        lines.append(f"### {rule['rule_id']} — {rule['severity']}")
        lines.append("")
        lines.append("| Model | Pass rate | Applicable | Failed | Skipped |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in models:
            lines.append(
                f"| {row['model']} | {_pct(row.get('pass_rate'))} | "
                f"{row['applicable']} | {row['failed']} | {row['skipped']} |"
            )
        lines.append("")
        evidence_lines: list[str] = []
        for row in models:
            if row["failed"] and (row.get("evidence") or row.get("evidence_detail")):
                evidence_lines.append(
                    f"> **{row['model']}** — "
                    + (row.get("evidence") or row.get("evidence_detail") or "")
                )
        if evidence_lines:
            lines.extend(evidence_lines)
            lines.append("")

    lines.append("## 7. Failures appendix")
    lines.append("")
    if report["failures"]:
        lines.append(
            "| Record | Model | Scenario | Prompt | Repeat | Status | Kind | "
            "Latency (ms) | Message |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in report["failures"]:
            message = (row.get("message") or "").replace("|", "\\|")
            lines.append(
                f"| `{row['record_id']}` | {row['model']} | {row['scenario']} | "
                f"{row['prompt']} | {row['repeat']} | {row['status']} | "
                f"{_cell(row.get('kind'))} | {_cell(row.get('latency_ms'))} | "
                f"{message} |"
            )
    else:
        lines.append("No record failed to produce an answer.")
    lines.append("")

    lines.append("## 8. What this result means")
    lines.append("")
    lines.append("> " + report["mandatory_paragraph"])
    lines.append("")
    lines.append("### Limitations generated from this sweep")
    lines.append("")
    for note in report["limitations"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("### What this benchmark does not measure")
    lines.append("")
    for note in report["does_not_measure"]:
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## 9. Reproduction")
    lines.append("")
    lines.append(f"Plan hash: `{header.get('plan_hash')}`")
    lines.append("")
    lines.append("Scores are recomputable offline from `records.jsonl`:")
    lines.append("")
    lines.append("```bash")
    for command in report["reproduction"].get("commands") or []:
        lines.append(command)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def report_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_report(
    sweep_dir: Path, report: Mapping[str, object] | None = None
) -> tuple[Path, Path]:
    """Write both artefacts atomically; return their paths."""
    report = report or build_report(sweep_dir)
    markdown_path = sweep_dir / config.REPORT_MARKDOWN
    json_path = sweep_dir / config.REPORT_JSON
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(report_json(report), encoding="utf-8")
    return markdown_path, json_path
