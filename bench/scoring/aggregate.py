"""Per-answer numbers, per-model summaries and the model-comparison verdict.

The formulas are rubric §9 verbatim, with one documented amendment: the judge
is phase 5, so ``J`` is ``None`` here. A composite computed without the judge is
**not** renormalised into a comparable 0-1 number — that would make a
judge-less sweep look like a judge-ful one. It keeps its 0.70 ceiling, is marked
``composite_partial``, and the verdict reports ``judge_missing`` rather than
crowning a winner on 70 % of the formula.

``R`` counts penalty units, not failed rules: P-01 is "major per missing
element" (rubric §5), so one failed outcome can cost more than one 25-point
step. Nothing else in the file interprets a rule's severity for itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .. import config
from ..plan import sha256_text
from . import stats
from .checks import RuleOutcome, Severity
from .rubric import Rubric, apply_rubric

SCORE_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# One answer
# ---------------------------------------------------------------------------


def _coverage_rules(rubric: Rubric) -> set[str]:
    return {
        rule.id for rule in rubric.rules if bool((rule.params or {}).get("coverage"))
    }


def _penalty_totals(outcomes: Iterable[RuleOutcome]) -> dict[str, int]:
    totals = {
        "blocker": 0,
        "major": 0,
        "minor": 0,
        "major_units": 0,
        "minor_units": 0,
        "failed": 0,
        "skipped": 0,
        "unknown_rule": 0,
    }
    for outcome in outcomes:
        if not outcome.applies:
            totals["skipped"] += 1
            if outcome.skipped_reason == "unknown_rule":
                totals["unknown_rule"] += 1
            continue
        if outcome.passed:
            continue
        totals["failed"] += 1
        units = max(1, outcome.penalty_units)
        if outcome.severity is Severity.BLOCKER:
            totals["blocker"] += 1
        elif outcome.severity is Severity.MAJOR:
            totals["major"] += 1
            totals["major_units"] += units
        else:
            totals["minor"] += 1
            totals["minor_units"] += units
    return totals


def composite(
    r: float | None,
    coverage: float | None,
    judge: float | None,
) -> tuple[float | None, bool]:
    """Rubric §9.1 composite, and whether it is missing the judge term.

    Returns ``(value, partial)``. ``value`` is ``None`` for a FAIL cell: the
    composite is defined on PASS cells only. When ``judge`` is ``None`` the two
    available terms are summed without renormalising, so the number stays on its
    real 0.70 scale and cannot be compared with a full composite by accident.
    """
    if r is None or coverage is None:
        return (None, True)
    if r == 0 or r < config.GATE_MIN_R:
        return (None, judge is None)
    value = config.COMPOSITE_WEIGHT_R * r / 100.0
    value += config.COMPOSITE_WEIGHT_COVERAGE * coverage
    if judge is None:
        return (round(value, 6), True)
    scaled = (judge - config.JUDGE_MIN) / (config.JUDGE_MAX - config.JUDGE_MIN)
    value += config.COMPOSITE_WEIGHT_JUDGE * scaled
    return (round(value, 6), False)


# The rubric names dimensions J-01..J-05; the judge's JSON schema uses the
# human names. Both are accepted so a stored score can be read either way.
_DIMENSION_NAMES = {
    "J-01": "actionability",
    "J-02": "specificity",
    "J-03": "prioritisation",
    "J-04": "honesty",
    "J-05": "tone",
}


def judge_value(dimensions: Mapping[str, float] | None, rubric: Rubric) -> float | None:
    """Weighted mean of the judge dimensions, or ``None`` without a judge."""
    if not dimensions:
        return None
    weights = rubric.judge.get("weights") or []
    names = rubric.judge.get("dimensions") or []
    total = 0.0
    weight_sum = 0.0
    for name, weight in zip(names, weights):
        score = dimensions.get(str(name))
        if score is None:
            score = dimensions.get(_DIMENSION_NAMES.get(str(name), ""))
        if score is None:
            continue
        total += float(score) * float(weight)
        weight_sum += float(weight)
    if weight_sum <= 0:
        return None
    return round(total / weight_sum, 6)


def score_answer(
    record: Mapping[str, object],
    outcomes: Sequence[RuleOutcome],
    rubric: Rubric,
    *,
    judge_dimensions: Mapping[str, float] | None = None,
    judge_status: str = "none",
    judge_meta: Mapping[str, object] | None = None,
) -> dict:
    """Turn one record's outcomes into the line ``scores.jsonl`` stores.

    ``judge_status`` is one of ``none`` (judge not run), ``ok``,
    ``judge_missing`` (the cell was deliberately not judged, for example with
    ``--judge-repeats``), ``judge-unstable`` or ``judge-invalid``. Only ``ok``
    contributes a value: an unstable, invalid or unjudged cell is excluded from
    the model mean, never imputed (rubric §8.4, §12.5.2).
    """
    if judge_status == "none" and judge_dimensions:
        judge_status = "ok"
    totals = _penalty_totals(outcomes)
    r: float | None
    if totals["blocker"]:
        r = 0.0
    else:
        r = max(
            0.0,
            100.0
            - config.POINTS_PER_MAJOR * totals["major_units"]
            - config.POINTS_PER_MINOR * totals["minor_units"],
        )
    gate = "pass" if totals["blocker"] == 0 and r >= config.GATE_MIN_R else "fail"

    coverage_rules = _coverage_rules(rubric)
    coverage_hits = sum(
        outcome.hits
        for outcome in outcomes
        if outcome.rule_id in coverage_rules and outcome.applies
    )
    coverage_total = sum(
        outcome.total
        for outcome in outcomes
        if outcome.rule_id in coverage_rules and outcome.applies
    )
    coverage = (coverage_hits / coverage_total) if coverage_total else None

    judge = judge_value(judge_dimensions, rubric) if judge_status == "ok" else None
    value, partial = composite(r, coverage, judge)
    if gate == "fail":
        value = None

    scopes = {
        outcome.grounding_scope for outcome in outcomes if outcome.grounding_scope
    }
    scope = "preview" if "preview" in scopes else ("full" if scopes else None)
    unknown_numbers = sum(outcome.unknown for outcome in outcomes if outcome.applies)
    answer = str(record.get("answer") or "")
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "scoring_id": _scoring_id(record, rubric),
        "scoring_version": rubric.version,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "record_id": record.get("record_id"),
        "sweep": record.get("sweep"),
        "plan_hash": record.get("plan_hash"),
        "model": {
            "key": (record.get("model") or {}).get("key"),
            "cohort": (record.get("model") or {}).get("cohort"),
            "fidelity": (record.get("model") or {}).get("fidelity"),
            "adapter": (record.get("model") or {}).get("adapter"),
        },
        "fixture": {
            "scenario": (record.get("fixture") or {}).get("scenario"),
            "version": (record.get("fixture") or {}).get("version"),
        },
        "prompt": {"id": (record.get("prompt") or {}).get("id")},
        "repeat": record.get("repeat"),
        "status": record.get("status"),
        "scored": True,
        "reason": "",
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "counts": totals,
        "unknown_rules": sorted(
            {
                outcome.rule_id
                for outcome in outcomes
                if outcome.skipped_reason == "unknown_rule"
            }
        ),
        "grounding": {"scope": scope, "unknown_numbers": unknown_numbers},
        "r": r,
        "gate": gate,
        "coverage": None if coverage is None else round(coverage, 6),
        "judge": judge,
        "judge_status": judge_status,
        "judge_unstable": judge_status == "judge-unstable",
        "judge_dimensions": dict(judge_dimensions) if judge_dimensions else None,
        "judge_meta": dict(judge_meta) if judge_meta else None,
        "composite": value,
        "composite_partial": partial,
        "words": len(answer.split()),
        "finish_reason": record.get("finish_reason"),
    }


def _scoring_id(record: Mapping[str, object], rubric: Rubric) -> str:
    raw = "|".join(
        (
            rubric.sha256,
            str(record.get("record_id") or ""),
            str(record.get("answer_sha256") or ""),
        )
    )
    return sha256_text(raw)[: config.RECORD_ID_CHARS]


def unscored_entry(record: Mapping[str, object], rubric: Rubric) -> dict:
    """A failed capture is a missing cell, never a zero score (rubric §9.2)."""
    status = str(record.get("status") or "error")
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "scoring_id": _scoring_id(record, rubric),
        "scoring_version": rubric.version,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "record_id": record.get("record_id"),
        "sweep": record.get("sweep"),
        "plan_hash": record.get("plan_hash"),
        "model": {
            "key": (record.get("model") or {}).get("key"),
            "cohort": (record.get("model") or {}).get("cohort"),
            "fidelity": (record.get("model") or {}).get("fidelity"),
            "adapter": (record.get("model") or {}).get("adapter"),
        },
        "fixture": {
            "scenario": (record.get("fixture") or {}).get("scenario"),
            "version": (record.get("fixture") or {}).get("version"),
        },
        "prompt": {"id": (record.get("prompt") or {}).get("id")},
        "repeat": record.get("repeat"),
        "status": status,
        "scored": False,
        "reason": status,
        "outcomes": [],
        "counts": {
            "blocker": 0,
            "major": 0,
            "minor": 0,
            "major_units": 0,
            "minor_units": 0,
            "failed": 0,
            "skipped": 0,
            "unknown_rule": 0,
        },
        "unknown_rules": [],
        "grounding": {"scope": None, "unknown_numbers": 0},
        "r": None,
        "gate": None,
        "coverage": None,
        "judge": None,
        "judge_status": "none",
        "judge_unstable": False,
        "judge_dimensions": None,
        "judge_meta": None,
        "composite": None,
        "composite_partial": True,
        "words": 0,
        "finish_reason": record.get("finish_reason"),
    }


def latest_records(records: Iterable[Mapping[str, object]]) -> list[dict]:
    """One record per ``record_id``, keeping the last attempt.

    A retried failure appends a second line for the same id; scoring the last
    attempt is what the resume rule in the runner means by "the answer".
    """
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for record in records:
        record_id = str(record.get("record_id") or "")
        if not record_id:
            continue
        if record_id not in by_id:
            order.append(record_id)
        by_id[record_id] = dict(record)
    return [by_id[record_id] for record_id in order]


def score_records(
    records: Iterable[Mapping[str, object]],
    rubric: Rubric,
    fixtures: Mapping[str, object],
    *,
    raw_dir: Path | None = None,
    judge_scorer: Callable[[Mapping[str, object], object], Mapping[str, object]]
    | None = None,
) -> list[dict]:
    """Score every record, skipping a fixture that is not loaded rather than guessing.

    ``judge_scorer`` is the optional phase-5 hook. It receives the record and
    the fixture and returns the ``judge_dimensions``/``judge_status``/
    ``judge_meta`` keyword arguments; the judge itself never runs when it is
    ``None``, so rescoring stays free.
    """
    entries: list[dict] = []
    for record in latest_records(records):
        status = str(record.get("status") or "")
        if status != "ok" or not record.get("answer"):
            entries.append(unscored_entry(record, rubric))
            continue
        scenario = str((record.get("fixture") or {}).get("scenario") or "")
        fixture = fixtures.get(scenario)
        if fixture is None:
            entries.append(unscored_entry(record, rubric))
            entries[-1]["reason"] = f"fixture {scenario!r} not loaded"
            continue
        outcomes = apply_rubric(record, fixture, rubric, raw_dir=raw_dir)
        judge_fields = (
            dict(judge_scorer(record, fixture)) if judge_scorer is not None else {}
        )
        entries.append(score_answer(record, outcomes, rubric, **judge_fields))
    return entries


def scores_jsonl(entries: Sequence[Mapping[str, object]]) -> str:
    """Deterministic JSONL: sorted by ``record_id`` so a rescore is byte-identical."""
    ordered = sorted(entries, key=lambda entry: str(entry.get("record_id") or ""))
    return "".join(
        json.dumps(entry, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        + "\n"
        for entry in ordered
    )


def write_scores(path: Path, entries: Sequence[Mapping[str, object]]) -> None:
    """Rewrite ``scores.jsonl`` atomically; rescoring is free and idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(scores_jsonl(entries))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


# ---------------------------------------------------------------------------
# Per model
# ---------------------------------------------------------------------------


def _value(entry: Mapping[str, object], *path: str) -> object:
    current: object = entry
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _scored(entries: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [entry for entry in entries if entry.get("scored")]


def summarise_model(
    key: str,
    entries: Sequence[Mapping[str, object]],
    *,
    min_answers: int,
    min_cells: int,
    unknown_rules: Sequence[str] = (),
) -> dict:
    """Rubric §9.2 metrics for one model, plus its eligibility.

    ``judge_mean`` is the mean over **PASS answers only** (rubric §9.2): a FAIL
    answer's usability score cannot enter the dominance condition, because the
    composite is undefined there and a high judge score would otherwise lift a
    model that failed the gate.
    """
    scored = _scored(entries)
    answers = len(scored)
    cells = {
        (
            str(_value(entry, "fixture", "scenario") or ""),
            str(_value(entry, "prompt", "id") or ""),
        )
        for entry in scored
    }
    blockers = sum(
        1 for entry in scored if int(_value(entry, "counts", "blocker") or 0) > 0
    )
    blocker_rate = blockers / answers if answers else 0.0
    wilson = stats.wilson_interval(blockers, answers)

    passes = [entry for entry in scored if entry.get("gate") == "pass"]
    gate_pass_rate = len(passes) / answers if answers else 0.0

    r_values = [
        float(entry["r"])
        for entry in passes
        if isinstance(entry.get("r"), (int, float))
    ]
    coverage_values = [
        float(entry["coverage"])
        for entry in scored
        if isinstance(entry.get("coverage"), (int, float))
    ]
    judge_values = [
        float(entry["judge"])
        for entry in passes
        if isinstance(entry.get("judge"), (int, float))
    ]
    unstable = sum(1 for entry in scored if entry.get("judge_unstable") is True)
    judge_invalid = sum(
        1 for entry in scored if entry.get("judge_status") == "judge-invalid"
    )
    judge_missing = sum(
        1 for entry in scored if entry.get("judge_status") == "judge_missing"
    )
    judge_attempted = any(
        entry.get("judge_status") not in (None, "none") for entry in scored
    )

    words = [float(entry.get("words") or 0) for entry in scored]
    truncated = sum(1 for entry in scored if entry.get("finish_reason") == "length")

    unknown = sorted(
        {rule_id for entry in scored for rule_id in (entry.get("unknown_rules") or [])}
        | set(unknown_rules)
    )

    reasons: list[str] = []
    attempted = len(entries)
    if attempted < min_answers:
        reasons.append(f"attempted {attempted} answers, minimum {min_answers}")
    if len(cells) < min_cells:
        reasons.append(f"{len(cells)} scorable cells, minimum {min_cells}")
    if unknown:
        reasons.append("rubric rules without an implementation: " + ", ".join(unknown))

    first = scored[0] if scored else entries[0] if entries else {}
    return {
        "key": key,
        "cohort": _value(first, "model", "cohort") or "unknown",
        "fidelity": _value(first, "model", "fidelity") or "unknown",
        "adapter": _value(first, "model", "adapter") or "unknown",
        "attempted": attempted,
        "answers": answers,
        "cells": len(cells),
        "blockers": blockers,
        "blocker_rate": round(blocker_rate, 6),
        "blocker_wilson": [round(wilson[0], 6), round(wilson[1], 6)],
        "gate_pass_rate": round(gate_pass_rate, 6),
        "r_median": _none_or_round(stats.median(r_values)),
        "r_iqr": _rounded_pair(stats.iqr(r_values)),
        "coverage_mean": _none_or_round(stats.mean(coverage_values)),
        "coverage_sd": _none_or_round(stats.stdev(coverage_values)),
        "judge_mean": _none_or_round(stats.mean(judge_values)),
        "judge_sd": _none_or_round(stats.stdev(judge_values)),
        "judge_answers": len(judge_values),
        "judge_instability": (
            round(unstable / answers, 6) if answers and judge_attempted else None
        ),
        "judge_invalid": judge_invalid,
        "judge_missing": judge_missing,
        "words_mean": _none_or_round(stats.mean(words)),
        "truncation_rate": round(truncated / answers, 6) if answers else None,
        "unknown_rules": unknown,
        "insufficient_evidence": bool(reasons),
        "reasons": reasons,
    }


def _none_or_round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _rounded_pair(
    value: tuple[float, float] | None,
) -> list[float] | None:
    if value is None:
        return None
    return [round(value[0], 6), round(value[1], 6)]


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _cell_keys(entries: Sequence[Mapping[str, object]]) -> set[tuple[str, str]]:
    return {
        (
            str(_value(entry, "fixture", "scenario") or ""),
            str(_value(entry, "prompt", "id") or ""),
        )
        for entry in _scored(entries)
    }


def _cell_quality(
    entries: Sequence[Mapping[str, object]], cell: tuple[str, str]
) -> tuple[float, float, float] | None:
    """Median (PASS, R, Coverage) for one cell.

    Repeats are within-cell noise (rubric §9.3), so the cell's value is the
    median of its repeats, not one arbitrary repeat. The tuple is compared
    lexicographically: a PASS beats a FAIL, then R, then Coverage.
    """
    rows = [
        entry
        for entry in _scored(entries)
        if (
            str(_value(entry, "fixture", "scenario") or ""),
            str(_value(entry, "prompt", "id") or ""),
        )
        == cell
    ]
    if not rows:
        return None
    passes = [1.0 if row.get("gate") == "pass" else 0.0 for row in rows]
    r_values = [float(row.get("r") or 0.0) for row in rows]
    coverage = [
        float(row["coverage"]) if isinstance(row.get("coverage"), (int, float)) else 0.0
        for row in rows
    ]
    return (
        float(stats.median(passes) or 0.0),
        float(stats.median(r_values) or 0.0),
        float(stats.median(coverage) or 0.0),
    )


def compare_models(
    left: Mapping[str, object],
    right: Mapping[str, object],
    left_entries: Sequence[Mapping[str, object]],
    right_entries: Sequence[Mapping[str, object]],
) -> dict:
    """The four conditions of rubric §9.2 for one ordered pair.

    ``left`` is the candidate for "better". The function never consults the
    composite: it is a reporting convenience, not the arbiter.
    """
    conditions: dict[str, dict] = {}
    reasons: list[str] = []

    # 1. blocker rate, with non-overlapping Wilson intervals (or both zero).
    left_rate = float(left.get("blocker_rate") or 0.0)
    right_rate = float(right.get("blocker_rate") or 0.0)
    left_interval = left.get("blocker_wilson") or [0.0, 1.0]
    right_interval = right.get("blocker_wilson") or [0.0, 1.0]
    both_zero = left_rate == 0.0 and right_rate == 0.0
    non_overlapping = float(left_interval[1]) < float(right_interval[0])
    blocker_ok = both_zero or (left_rate < right_rate and non_overlapping)
    conditions["blocker_rate"] = {
        "passed": blocker_ok,
        "left": left_rate,
        "right": right_rate,
        "left_interval": list(left_interval),
        "right_interval": list(right_interval),
        "detail": (
            "both records are blocker-free"
            if both_zero
            else "left rate is lower with non-overlapping intervals"
            if blocker_ok
            else "the blocker-rate interval overlaps or is not lower"
        ),
    }

    # 2. dominance on median R, mean Coverage and mean J.
    left_judge = left.get("judge_mean")
    right_judge = right.get("judge_mean")
    judge_missing = left_judge is None or right_judge is None
    legs = {
        "r_median": (left.get("r_median"), right.get("r_median")),
        "coverage_mean": (left.get("coverage_mean"), right.get("coverage_mean")),
        "judge_mean": (left_judge, right_judge),
    }
    if judge_missing:
        conditions["dominance"] = {
            "passed": False,
            "detail": "mean J is absent, so §9.2 condition 2 is not evaluable",
            "legs": {name: list(pair) for name, pair in legs.items()},
        }
        reasons.append("judge_missing")
    else:
        at_least = all(
            pair[0] is not None
            and pair[1] is not None
            and float(pair[0]) >= float(pair[1])
            for pair in legs.values()
        )
        strictly = any(
            pair[0] is not None
            and pair[1] is not None
            and float(pair[0]) > float(pair[1])
            for pair in legs.values()
        )
        dominance_ok = bool(at_least and strictly)
        conditions["dominance"] = {
            "passed": dominance_ok,
            "detail": (
                "at least as good on every metric, strictly better on one"
                if dominance_ok
                else "not dominant on median R, mean Coverage and mean J"
            ),
            "legs": {name: list(pair) for name, pair in legs.items()},
        }

    # 3. paired sign test over the cells the two models share.
    cells = sorted(_cell_keys(left_entries) & _cell_keys(right_entries))
    wins = losses = ties = 0
    for cell in cells:
        left_value = _cell_quality(left_entries, cell)
        right_value = _cell_quality(right_entries, cell)
        if left_value is None or right_value is None:
            continue
        if left_value > right_value:
            wins += 1
        elif left_value < right_value:
            losses += 1
        else:
            ties += 1
    p_value = stats.sign_test(wins, losses)
    needed = stats.sign_test_threshold(len(cells)) if cells else len(cells) + 1
    share = wins / len(cells) if cells else 0.0
    sign_ok = (
        bool(cells)
        and wins > losses
        and wins >= needed
        and share >= config.SIGN_TEST_MIN_WIN_SHARE
        and p_value < 0.05
    )
    conditions["sign_test"] = {
        "passed": sign_ok,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "cells": len(cells),
        "needed": needed,
        "p_two_sided": round(p_value, 6),
        "detail": (
            f"{wins} of {len(cells)} cells favour the left model (p = {p_value:.3f})"
        ),
    }

    # 4. no excluded unstable cell flips the direction.
    # A per-cell instability flag is the only honest basis for this: a rate
    # cannot say which direction the excluded cells pointed. With the judge
    # absent every flag is false, so the condition holds vacuously; once phase 5
    # writes ``judge_unstable`` per cell, any unstable cell makes the verdict
    # conservative rather than guessing its effect.
    unstable_cells = sum(
        1
        for entry in list(left_entries) + list(right_entries)
        if entry.get("judge_unstable") is True
    )
    condition4_ok = unstable_cells == 0
    conditions["instability"] = {
        "passed": condition4_ok,
        "unstable_cells": unstable_cells,
        "detail": (
            "no cell was excluded for judge instability"
            if condition4_ok
            else f"{unstable_cells} unstable cell(s) could change the direction"
        ),
    }

    if judge_missing:
        status = "insufficient_evidence"
    elif all(condition["passed"] for condition in conditions.values()):
        status = "better"
    else:
        status = "no_distinguishable_difference"
        if not blocker_ok:
            reasons.append("blocker_rate")
        if not conditions["dominance"]["passed"]:
            reasons.append("dominance")
        if not sign_ok:
            reasons.append("sign_test")
        if not condition4_ok:
            reasons.append("instability")
    return {
        "cohort": left.get("cohort") or right.get("cohort"),
        "left": left.get("key"),
        "right": right.get("key"),
        "status": status,
        "winner": left.get("key") if status == "better" else None,
        "reasons": sorted(set(reasons)),
        "conditions": conditions,
    }


def aggregate(
    entries: Sequence[Mapping[str, object]],
    rubric: Rubric,
    *,
    min_answers: int | None = None,
    min_cells: int | None = None,
    judge_model: str | None = None,
    judge_prompt_sha256: str | None = None,
) -> dict:
    """Per-model summary plus every within-cohort pair verdict.

    Models are grouped by ``model.cohort``. A production and a proxy model are
    never placed in one verdict (spec §7.5); their numbers may share a table,
    with the fidelity column visible, but the comparison is within a cohort.
    """
    min_answers = min_answers or config.BENCH_MIN_ANSWERS
    min_cells = min_cells or config.BENCH_MIN_CELLS
    by_model: dict[str, list[Mapping[str, object]]] = {}
    for entry in entries:
        key = str(_value(entry, "model", "key") or "")
        if not key:
            continue
        by_model.setdefault(key, []).append(entry)

    models: list[dict] = []
    for key in sorted(by_model):
        models.append(
            summarise_model(
                key,
                by_model[key],
                min_answers=min_answers,
                min_cells=min_cells,
                unknown_rules=rubric.unknown_rules,
            )
        )

    by_cohort: dict[str, list[dict]] = {}
    for model in models:
        by_cohort.setdefault(str(model["cohort"]), []).append(model)

    verdicts: list[dict] = []
    for cohort in sorted(by_cohort):
        members = sorted(by_cohort[cohort], key=lambda model: str(model["key"]))
        eligible = [
            model for model in members if not model.get("insufficient_evidence")
        ]
        for index, left in enumerate(eligible):
            for right in eligible[index + 1 :]:
                verdicts.append(
                    compare_models(
                        left,
                        right,
                        by_model[str(left["key"])],
                        by_model[str(right["key"])],
                    )
                )

    unknown = sorted(
        {rule_id for model in models for rule_id in model.get("unknown_rules") or []}
    )
    judge_meta = next(
        (entry.get("judge_meta") for entry in entries if entry.get("judge_meta")),
        None,
    )
    if isinstance(judge_meta, Mapping):
        judge_model = judge_model or judge_meta.get("model")
        judge_prompt_sha256 = judge_prompt_sha256 or judge_meta.get("prompt_sha256")
    judged = [
        entry
        for entry in entries
        if entry.get("judge_status") not in (None, "none", "judge_missing")
    ]
    unstable_cells = sum(1 for entry in judged if entry.get("judge_unstable") is True)
    unstable_rate = (unstable_cells / len(judged)) if judged else 0.0
    # Provisional certification (rubric §12.7): a judge that is unstable on
    # more than 15% of the scored cells does not get its J published.
    judge_withheld = bool(judged) and (
        unstable_rate > config.JUDGE_GATE_MAX_UNSTABLE_RATE
    )
    withheld_reason = (
        "unstable-cell rate "
        f"{unstable_rate:.1%} > {config.JUDGE_GATE_MAX_UNSTABLE_RATE:.0%} "
        f"({unstable_cells}/{len(judged)} judged cells)"
        if judge_withheld
        else ""
    )
    if judge_withheld:
        for verdict in verdicts:
            verdict["status"] = "insufficient_evidence"
            verdict["winner"] = None
            verdict["reasons"] = sorted(
                set(verdict.get("reasons") or ()) | {"judge_withheld"}
            )
            dominance = verdict["conditions"].get("dominance") or {}
            dominance["passed"] = False
            dominance["detail"] = f"J withheld: {withheld_reason}"
            verdict["conditions"]["dominance"] = dominance
    judge_present = any(entry.get("judge") is not None for entry in entries)
    if judge_present:
        composite_note = (
            "composite includes the judge term; it is a reporting convenience "
            "and is never used to rank a model"
        )
    else:
        composite_note = (
            "composite excludes the judge term: it is a 0.70-scale partial value, "
            "marked composite_partial, and is never used to rank"
        )
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "scoring_version": rubric.version,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "judge": {
            "implemented": bool(rubric.judge.get("implemented")),
            "dimensions": list(rubric.judge.get("dimensions") or []),
            "weights": list(rubric.judge.get("weights") or []),
            "model": judge_model,
            "prompt_sha256": judge_prompt_sha256,
            "gate": config.JUDGE_GATE,
            "present": judge_present,
            "missing": not judge_present,
            "judged_cells": len(judged),
            "unstable_cells": unstable_cells,
            "unstable_rate": round(unstable_rate, 6),
            "withheld": judge_withheld,
            "withheld_reason": withheld_reason,
        },
        "composite_note": composite_note,
        "records": len(entries),
        "answers": sum(model["answers"] for model in models),
        "models": models,
        "cohorts": {
            cohort: [model["key"] for model in members]
            for cohort, members in sorted(by_cohort.items())
        },
        "verdicts": verdicts,
        "unknown_rules": unknown,
        "insufficient_evidence": [
            model["key"] for model in models if model["insufficient_evidence"]
        ],
    }
