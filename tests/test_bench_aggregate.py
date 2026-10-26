"""Aggregation, the composite, the verdict and the offline ``score`` pass.

The formulas are rubric §9. The one amendment is that the judge is phase 5:
``J`` is ``None``, so the composite is marked partial and never renormalised
into a number that could be compared with a judge-ful sweep. The verdict then
reports ``judge_missing`` instead of crowning a winner on 70 % of the formula.
"""

from __future__ import annotations

import json

import pytest

from bench import config, records
from bench.cli import main
from bench.fixtures import load_fixtures
from bench.scoring.aggregate import (
    aggregate,
    compare_models,
    composite,
    score_answer,
    score_records,
    scores_jsonl,
    summarise_model,
    unscored_entry,
    write_scores,
)
from bench.scoring.checks import RuleOutcome, Severity
from bench.scoring.rubric import load_rubric

FIXTURE = load_fixtures(["healthy"])[0]
RUBRIC = load_rubric()


def make_outcome(
    rule_id: str,
    severity: Severity,
    passed: bool,
    *,
    hits: int = 1,
    total: int = 1,
    penalty_units: int | None = None,
) -> RuleOutcome:
    return RuleOutcome(
        rule_id=rule_id,
        severity=severity,
        applies=True,
        passed=passed,
        hits=hits,
        total=total,
        penalty_units=penalty_units
        if penalty_units is not None
        else (0 if passed else 1),
    )


def make_record(
    record_id: str = "rec-1",
    *,
    scenario: str = "healthy",
    prompt: str = "this_week",
    model: str = "model-a",
    cohort: str = "production",
    answer: str = "Your load is 580.0 units.",
    repeat: int = 0,
    status: str = "ok",
) -> dict:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "sweep": "test",
        "plan_hash": "plan",
        "status": status,
        "answer": answer,
        "answer_sha256": "sha-" + record_id,
        "model": {
            "key": model,
            "cohort": cohort,
            "fidelity": cohort,
            "adapter": "fake",
        },
        "fixture": {
            "scenario": scenario,
            "version": FIXTURE.version,
            "snapshot_sha256": FIXTURE.snapshot_sha256,
        },
        "prompt": {"id": prompt},
        "repeat": repeat,
        "finish_reason": "stop",
        "context": {"chars": 8000, "truncated": False},
        "tool_calls": [],
    }


def entry(
    *,
    model: str = "model-a",
    cohort: str = "production",
    scenario: str = "healthy",
    prompt: str = "this_week",
    r: float = 75.0,
    coverage: float = 0.8,
    gate: str = "pass",
    judge: float | None = None,
    judge_status: str | None = None,
    blockers: int = 0,
) -> dict:
    return {
        "record_id": f"{model}-{scenario}-{prompt}",
        "model": {"key": model, "cohort": cohort, "fidelity": cohort},
        "fixture": {"scenario": scenario},
        "prompt": {"id": prompt},
        "scored": True,
        "gate": gate,
        "r": r,
        "coverage": coverage,
        "judge": judge,
        "judge_status": judge_status or ("ok" if judge is not None else "none"),
        "counts": {"blocker": blockers, "major": 1 if r < 100 else 0, "minor": 0},
        "words": 120,
        "finish_reason": "stop",
        "unknown_rules": [],
    }


# ---------------------------------------------------------------------------
# Per answer
# ---------------------------------------------------------------------------


def test_bench_composite_matches_rubric():
    """R = 100 - 25*1 = 75, Coverage 4/5, J = 3 -> 0.45*.75 + .25*.8 + .30*.5."""
    outcomes = [
        make_outcome("P-01", Severity.MAJOR, False, hits=4, total=5),
        make_outcome("S-03", Severity.MINOR, True),
    ]
    score = score_answer(
        make_record(),
        outcomes,
        RUBRIC,
        judge_dimensions={"J-01": 3, "J-02": 3, "J-03": 3, "J-04": 3, "J-05": 3},
    )
    assert score["r"] == 75.0
    assert score["coverage"] == pytest.approx(0.8)
    assert score["judge"] == pytest.approx(3.0)
    assert score["gate"] == "pass"
    assert score["composite"] == pytest.approx(0.6875)
    assert score["composite_partial"] is False

    partial, is_partial = composite(75.0, 0.8, None)
    assert partial == pytest.approx(0.5375), "0.45*0.75 + 0.25*0.8, not renormalised"
    assert is_partial is True


def test_bench_blocker_zeroes_r_and_fails_gate():
    outcomes = [
        make_outcome("X-01", Severity.BLOCKER, False),
        make_outcome("G-01", Severity.MAJOR, False),
        make_outcome("S-03", Severity.MINOR, False),
        make_outcome("P-01", Severity.MAJOR, True, hits=5, total=5),
    ]
    score = score_answer(make_record(), outcomes, RUBRIC)
    assert score["r"] == 0.0
    assert score["gate"] == "fail"
    assert score["counts"]["blocker"] == 1
    assert score["composite"] is None
    assert score["coverage"] == pytest.approx(1.0)


def test_bench_major_per_missing_element_costs_more_than_one_step():
    outcomes = [
        make_outcome("P-01", Severity.MAJOR, False, hits=3, total=5, penalty_units=2)
    ]
    score = score_answer(make_record(), outcomes, RUBRIC)
    assert score["r"] == 50.0
    assert score["counts"]["major_units"] == 2


def test_bench_unscored_record_is_a_missing_cell_not_zero():
    record = make_record(status="timeout")
    record["answer"] = ""
    entry = unscored_entry(record, RUBRIC)
    assert entry["scored"] is False
    assert entry["r"] is None
    assert entry["gate"] is None
    assert entry["reason"] == "timeout"


def test_bench_score_answer_shape_is_stable():
    score = score_answer(
        make_record(), [make_outcome("S-03", Severity.MINOR, True)], RUBRIC
    )
    for key in (
        "schema_version",
        "scoring_id",
        "rubric_sha256",
        "record_id",
        "model",
        "fixture",
        "prompt",
        "outcomes",
        "counts",
        "r",
        "gate",
        "coverage",
        "judge",
        "composite",
        "composite_partial",
    ):
        assert key in score
    assert (
        score["scoring_id"]
        == score_answer(
            make_record(), [make_outcome("S-03", Severity.MINOR, True)], RUBRIC
        )["scoring_id"]
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _cells(model: str, *, better_on=None) -> list[dict]:
    """15 cells for one model, optionally making every cell better than the rival."""
    scenarios = ("healthy", "red_flags", "calibrating")
    prompts = ("this_week", "load_change", "intensity", "ready_10k", "review_4_weeks")
    rows = []
    for scenario in scenarios:
        for prompt in prompts:
            rows.append(
                entry(
                    model=model,
                    scenario=scenario,
                    prompt=prompt,
                    r=90.0 if better_on else 75.0,
                    coverage=0.5 if better_on else 0.8,
                    judge=4.0 if better_on else 3.0,
                )
            )
    return rows


def _summary(key: str, entries: list[dict]) -> dict:
    return summarise_model(key, entries, min_answers=1, min_cells=1)


def test_bench_verdict_requires_dominance():
    """A higher composite with worse coverage is not a win."""
    left = _cells("model-a", better_on=True)  # R 90, coverage .5, J 4
    right = _cells("model-b")  # R 75, coverage .8, J 3
    left_summary = _summary("model-a", left)
    right_summary = _summary("model-b", right)
    # Composite would favour A (0.45*.9 + .25*.5 + .30*.75 = .755)
    # over B (0.45*.75 + .25*.8 + .30*.5 = .6875).
    assert composite(90.0, 0.5, 4.0)[0] > composite(75.0, 0.8, 3.0)[0]
    verdict = compare_models(left_summary, right_summary, left, right)
    assert verdict["status"] == "no_distinguishable_difference"
    assert verdict["winner"] is None
    assert verdict["conditions"]["dominance"]["passed"] is False


def test_bench_verdict_declares_a_dominant_model():
    left = _cells("model-a", better_on=True)
    right = _cells("model-b")
    # Make the left strictly better on every leg, including coverage.
    for row in left:
        row["coverage"] = 0.9
    verdict = compare_models(
        _summary("model-a", left), _summary("model-b", right), left, right
    )
    assert verdict["status"] == "better"
    assert verdict["winner"] == "model-a"
    assert verdict["conditions"]["sign_test"]["wins"] == 15


def test_bench_verdict_unstable_cell_blocks_a_crown():
    left = _cells("model-a", better_on=True)
    right = _cells("model-b")
    for row in left:
        row["coverage"] = 0.9
    left[0]["judge_unstable"] = True
    verdict = compare_models(
        _summary("model-a", left), _summary("model-b", right), left, right
    )
    assert verdict["status"] == "no_distinguishable_difference"
    assert verdict["conditions"]["instability"]["passed"] is False
    assert verdict["conditions"]["instability"]["unstable_cells"] == 1


def test_bench_verdict_reports_missing_judge():
    left = _cells("model-a", better_on=True)
    right = _cells("model-b")
    for row in left + right:
        row["judge"] = None
    left_summary = _summary("model-a", left)
    right_summary = _summary("model-b", right)
    verdict = compare_models(left_summary, right_summary, left, right)
    assert verdict["status"] == "insufficient_evidence"
    assert "judge_missing" in verdict["reasons"]
    assert verdict["winner"] is None


def test_bench_verdict_insufficient_cells():
    entries = [
        entry(scenario="healthy", prompt=prompt, r=80.0) for prompt in ("this_week",)
    ] * 6
    summary = summarise_model("model-a", entries, min_answers=1, min_cells=15)
    assert summary["insufficient_evidence"] is True
    assert any("scorable cells" in reason for reason in summary["reasons"])
    assert summary["r_median"] is not None, "insufficient evidence is not zero scores"

    report = aggregate(entries, RUBRIC, min_answers=1, min_cells=15)
    assert report["insufficient_evidence"] == ["model-a"]
    assert report["verdicts"] == []


def test_bench_unknown_rule_blocks_verdict():
    from dataclasses import replace

    unknown = replace(
        RUBRIC,
        rules=RUBRIC.rules
        + (replace(RUBRIC.rules[0], id="Z-99", check="not_implemented", params={}),),
        unknown_rules=("Z-99",),
    )
    entries = [
        score_answer(
            make_record(record_id="rec-1"),
            [make_outcome("S-03", Severity.MINOR, True)],
            unknown,
        )
    ]
    # The unknown rule only appears when the rubric is applied; here the
    # aggregate must still count the rubric's own unknown list.
    report = aggregate(entries, unknown, min_answers=1, min_cells=1)
    assert report["unknown_rules"] == ["Z-99"]
    assert report["models"][0]["insufficient_evidence"] is True
    assert report["verdicts"] == []


def test_bench_cohorts_never_ranked_together():
    production_a = _cells("prod-a", better_on=True)
    production_b = _cells("prod-b")
    proxy = _cells("proxy-c", better_on=True)
    for row in proxy:
        row["model"]["cohort"] = "proxy"
        row["model"]["fidelity"] = "proxy"
    entries = production_a + production_b + proxy
    report = aggregate(entries, RUBRIC, min_answers=1, min_cells=1)
    assert report["cohorts"] == {
        "production": ["prod-a", "prod-b"],
        "proxy": ["proxy-c"],
    }
    assert len(report["verdicts"]) == 1, "only the two production models are compared"
    assert all("proxy" not in (v["left"], v["right"]) for v in report["verdicts"])


def test_bench_aggregate_reports_ties():
    left = _cells("model-a")
    right = _cells("model-b")
    verdict = compare_models(
        _summary("model-a", left), _summary("model-b", right), left, right
    )
    assert verdict["status"] != "better"
    assert verdict["winner"] is None


# ---------------------------------------------------------------------------
# Offline, idempotent scoring
# ---------------------------------------------------------------------------


def _write_records(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(records.serialize_record(row) + "\n")


def test_bench_score_does_not_call_the_model(tmp_path, monkeypatch):
    """Rescoring is free: no provider, no HTTP, no subprocess."""

    def explode(*_args, **_kwargs):
        raise AssertionError("score must not call a model")

    monkeypatch.setattr("app.coach_llm.run_chat", explode)
    monkeypatch.setattr("app.coach_llm.chat", explode)
    monkeypatch.setattr("bench.cli.ADAPTERS", {})

    rows = [
        make_record("rec-1", answer="Your load is 580.0 units."),
        make_record("rec-2", prompt="review_4_weeks", answer="Your CTL is 63.7."),
    ]
    _write_records(tmp_path / config.RECORDS_FILENAME, rows)

    assert main(["score", str(tmp_path), "--quiet"]) == 0
    first = (tmp_path / config.SCORES_FILENAME).read_bytes()
    assert first.endswith(b"\n")

    assert main(["score", str(tmp_path), "--quiet"]) == 0
    second = (tmp_path / config.SCORES_FILENAME).read_bytes()
    assert second == first, "rescoring must be idempotent"


def test_bench_score_rejects_a_foreign_fixture(tmp_path, monkeypatch):
    rows = [make_record("rec-1")]
    rows[0]["fixture"]["snapshot_sha256"] = "0" * 64
    _write_records(tmp_path / config.RECORDS_FILENAME, rows)
    assert main(["score", str(tmp_path), "--quiet"]) == 2


def test_bench_score_writes_one_line_per_record(tmp_path):
    rows = [
        make_record("rec-1"),
        make_record("rec-2", answer="", status="timeout"),
        make_record("rec-3", prompt="load_change", answer="Your load rose 60%."),
    ]
    _write_records(tmp_path / config.RECORDS_FILENAME, rows)
    assert main(["score", str(tmp_path), "--quiet"]) == 0
    lines = (tmp_path / config.SCORES_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [row["record_id"] for row in parsed] == ["rec-1", "rec-2", "rec-3"]
    assert parsed[1]["scored"] is False


def test_bench_score_keeps_the_last_attempt_for_a_record(tmp_path):
    failed = make_record("rec-1", status="timeout", answer="")
    retried = make_record("rec-1", answer="Your load is 580.0 units.")
    _write_records(tmp_path / config.RECORDS_FILENAME, [failed, retried])
    assert main(["score", str(tmp_path), "--quiet"]) == 0
    lines = (tmp_path / config.SCORES_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["scored"] is True


def test_bench_scores_jsonl_is_sorted():
    rows = [
        score_answer(
            make_record("rec-b"), [make_outcome("S-03", Severity.MINOR, True)], RUBRIC
        ),
        score_answer(
            make_record("rec-a"), [make_outcome("S-03", Severity.MINOR, True)], RUBRIC
        ),
    ]
    lines = scores_jsonl(rows).splitlines()
    assert [json.loads(line)["record_id"] for line in lines] == ["rec-a", "rec-b"]


def test_bench_write_scores_is_atomic(tmp_path):
    path = tmp_path / "scores.jsonl"
    rows = [
        score_answer(
            make_record(), [make_outcome("S-03", Severity.MINOR, True)], RUBRIC
        )
    ]
    write_scores(path, rows)
    write_scores(path, rows)
    assert json.loads(path.read_text(encoding="utf-8"))["record_id"] == "rec-1"
    assert not list(tmp_path.glob("*.tmp"))


def test_bench_score_records_end_to_end():
    rows = [
        make_record("rec-1"),
        make_record("rec-2", scenario="calibrating", prompt="intensity"),
    ]
    fixtures = {"healthy": FIXTURE, "calibrating": load_fixtures(["calibrating"])[0]}
    entries = score_records(rows, RUBRIC, fixtures)
    assert len(entries) == 2
    assert all(entry["scored"] for entry in entries)
    assert all(entry["rubric_sha256"] == RUBRIC.sha256 for entry in entries)
    # P-01's list is the coverage denominator; every prompt has a checklist.
    assert entries[0]["coverage"] is not None


# ---------------------------------------------------------------------------
# Judge aggregation: PASS-only mean, explicit judge_missing
# ---------------------------------------------------------------------------


def test_bench_judge_mean_is_pass_only():
    """Rubric §9.2: a FAIL answer's usability score cannot enter the mean."""
    rows = [
        entry(scenario="healthy", judge=1.0, gate="pass"),
        entry(scenario="red_flags", judge=5.0, gate="fail", r=0.0, coverage=0.8),
    ]
    summary = _summary("model-a", rows)
    assert summary["judge_answers"] == 1
    assert summary["judge_mean"] == 1.0


def test_bench_judge_missing_is_counted_and_never_imputed():
    rows = [
        entry(scenario="healthy", judge=3.0),
        entry(scenario="red_flags", judge=None, judge_status="judge_missing"),
        entry(scenario="calibrating", judge=None, judge_status="judge_missing"),
    ]
    summary = _summary("model-a", rows)

    assert summary["judge_missing"] == 2
    assert summary["judge_mean"] == 3.0, "the unjudged cells add nothing"
    assert summary["judge_answers"] == 1
