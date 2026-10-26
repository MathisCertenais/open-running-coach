"""Report rendering: order, blockers first, verdicts from aggregate, determinism.

The report is the artefact that decides a model, so these tests pin the parts
that would let it mislead: a composite-led ranking, a cross-cohort comparison,
a missing "insufficient evidence" line, or a report that changes between two
runs over the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench import config
from bench.report import (
    MANDATORY_PARAGRAPH,
    build_report,
    render_markdown,
    report_json,
    write_report,
)
from bench.scoring.rubric import load_rubric

SCENARIOS = ("healthy", "red_flags", "calibrating")
PROMPTS = ("this_week", "load_change", "intensity", "ready_10k", "review_4_weeks")
RUBRIC = load_rubric()


def make_entry(
    model: str,
    scenario: str,
    prompt: str,
    *,
    r: float = 75.0,
    coverage: float = 0.8,
    judge: float | None = 3.0,
    gate: str = "pass",
    cohort: str = "production",
    blocker: int = 0,
    major: int = 1,
    minor: int = 1,
    repeat: int = 0,
    plan_hash: str = "plan-hash",
    rubric_sha256: str | None = None,
    judge_unstable: bool = False,
) -> dict:
    return {
        "record_id": f"{model}-{scenario}-{prompt}-{repeat}",
        "sweep": "unit",
        "plan_hash": plan_hash,
        "rubric_sha256": rubric_sha256 or RUBRIC.sha256,
        "model": {
            "key": model,
            "cohort": cohort,
            "fidelity": cohort,
            "adapter": "fake",
        },
        "fixture": {"scenario": scenario, "version": 1},
        "prompt": {"id": prompt},
        "repeat": repeat,
        "status": "ok",
        "scored": True,
        "gate": gate,
        "r": r,
        "coverage": coverage,
        "judge": judge,
        "judge_status": "ok" if judge is not None else "none",
        "judge_unstable": judge_unstable,
        "judge_dimensions": None,
        "judge_meta": (
            {"model": "judge-x", "prompt_sha256": "judge-prompt", "calls": 3}
            if judge is not None
            else None
        ),
        "counts": {"blocker": blocker, "major": major, "minor": minor},
        "words": 120,
        "finish_reason": "stop",
        "unknown_rules": [],
        "outcomes": [
            {
                "rule_id": "S-03",
                "severity": "minor",
                "applies": True,
                "passed": False,
                "hits": 0,
                "total": 1,
                "pass_rate": 0.0,
                "evidence": "This answer has a failing span worth quoting.",
                "detail": "too long",
                "grounding_scope": None,
                "unknown": 0,
                "skipped_reason": "",
                "penalty_units": 1,
            },
            {
                "rule_id": "P-01",
                "severity": "major",
                "applies": True,
                "passed": True,
                "hits": 3,
                "total": 3,
                "pass_rate": 1.0,
                "evidence": "",
                "detail": "",
                "grounding_scope": None,
                "unknown": 0,
                "skipped_reason": "",
                "penalty_units": 0,
            },
        ],
    }


def make_records(entries: list[dict]) -> list[dict]:
    records = []
    for entry in entries:
        records.append(
            {
                "record_id": entry["record_id"],
                "sweep": "unit",
                "plan_hash": "plan-hash",
                "started_at": "2026-10-26T00:00:00Z",
                "model": entry["model"],
                "fixture": entry["fixture"],
                "prompt": entry["prompt"],
                "repeat": entry["repeat"],
                "status": entry["status"],
                "answer": "An answer.",
                "error": None,
                "latency_ms": 100,
                "latency_kind": "http_roundtrip",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "source": "provider",
                },
                "cost_usd": 0.001,
                "context": {"chars": 8000, "truncated": False},
            }
        )
    return records


def write_sweep(tmp_path: Path, entries: list[dict]) -> Path:
    sweep = tmp_path / config.SWEEPS_DIRNAME / "unit"
    sweep.mkdir(parents=True)
    meta = {
        "schema_version": 1,
        "sweep": "unit",
        "generated_at": "2026-10-26T00:00:00Z",
        "completed_at": "2026-10-26T01:00:00Z",
        "git_sha": "test-sha",
        "prices_as_of": "2026-10-26",
        "system_prompt": {"sha256": "system-hash"},
        "judge_model": "judge-x",
        "plan": {
            "plan_hash": "plan-hash",
            "repeats": 3,
            "models": sorted({entry["model"]["key"] for entry in entries}),
            "fixtures": [
                {
                    "scenario": scenario,
                    "version": 1,
                    "snapshot_sha256": f"snapshot-{scenario}",
                    "tool_context_sha256": f"tool-{scenario}",
                }
                for scenario in SCENARIOS
            ],
            "prompts": [
                {"id": prompt, "sha256": f"prompt-{prompt}"} for prompt in PROMPTS
            ],
        },
    }
    (sweep / config.META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
    with (sweep / config.RECORDS_FILENAME).open("w", encoding="utf-8") as handle:
        for record in make_records(entries):
            handle.write(json.dumps(record) + "\n")
    with (sweep / config.SCORES_FILENAME).open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return sweep


def full_cells(model: str, *, repeats: int = 3, **kwargs) -> list[dict]:
    return [
        make_entry(model, scenario, prompt, repeat=repeat, **kwargs)
        for repeat in range(repeats)
        for scenario in SCENARIOS
        for prompt in PROMPTS
    ]


def test_bench_report_sections(tmp_path):
    entries = full_cells("model-a") + full_cells("model-b")
    entries[0]["outcomes"].append(
        {
            "rule_id": "I-02",
            "severity": "major",
            "applies": False,
            "passed": None,
            "hits": 0,
            "total": 0,
            "pass_rate": None,
            "evidence": "",
            "detail": "payload gap",
            "grounding_scope": None,
            "unknown": 0,
            "skipped_reason": "payload_gap",
            "penalty_units": 0,
        }
    )
    sweep = write_sweep(tmp_path, entries)
    report = build_report(sweep)
    markdown = render_markdown(report)

    headings = [
        "## 1. Header",
        "## 2. Blocker rate (read this first)",
        "## 3. Verdict",
        "## 4. Per-model metrics",
        "## 5. Per-cell results",
        "## 6. Per-rule detail",
        "## 7. Failures appendix",
        "## 8. What this result means",
        "## 9. Reproduction",
    ]
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions), "sections must be in spec §8 order"
    assert markdown.index("## 2. Blocker rate") < markdown.index("Composite")
    assert MANDATORY_PARAGRAPH in markdown
    assert "What this benchmark does not measure" in markdown
    assert "Limitations generated from this sweep" in markdown
    assert "Fidelity mix" in markdown
    assert "Fixture healthy.v1" in markdown
    assert "Truncated contexts" in markdown
    assert "Payload gaps" in markdown and "I-02" in markdown
    assert "Per-cell rows are descriptive only" in markdown


def test_bench_report_aggregate_reports_ties(tmp_path):
    entries = full_cells("model-a") + full_cells("model-b")
    sweep = write_sweep(tmp_path, entries)
    report = build_report(sweep)
    markdown = render_markdown(report)
    assert all(verdict["status"] != "better" for verdict in report["verdicts"])
    assert "No distinguishable difference between model-a and model-b" in markdown
    assert "is better than" not in markdown
    assert "no_distinguishable_difference" in report_json(report)


def test_bench_report_insufficient_evidence(tmp_path):
    entries = full_cells("model-a") + full_cells("model-b")[:3]
    sweep = write_sweep(tmp_path, entries)
    report = build_report(sweep)
    markdown = render_markdown(report)
    assert any(item["model"] == "model-b" for item in report["insufficient_evidence"])
    assert "**model-b** (production) — insufficient evidence" in markdown
    assert "not ranked" in markdown


def test_bench_report_never_ranks_composite(tmp_path):
    """A higher composite with worse coverage is still "no distinguishable difference"."""
    left = full_cells("model-a", r=90.0, coverage=0.5, judge=4.0)
    right = full_cells("model-b", r=75.0, coverage=0.8, judge=3.0)
    edges = {
        "model-a": 0.45 * 0.9 + 0.25 * 0.5 + 0.30 * 0.75,
        "model-b": 0.45 * 0.75 + 0.25 * 0.8 + 0.30 * 0.5,
    }
    assert edges["model-a"] > edges["model-b"]
    sweep = write_sweep(tmp_path, left + right)
    report = build_report(sweep)
    markdown = render_markdown(report)
    assert report["verdicts"][0]["status"] == "no_distinguishable_difference"
    assert "is better than" not in markdown
    assert "Composite is deliberately absent from this table" in markdown


def test_bench_report_is_deterministic(tmp_path):
    entries = full_cells("model-a") + full_cells("model-b")
    sweep = write_sweep(tmp_path, entries)
    first = build_report(sweep)
    second = build_report(sweep)
    assert render_markdown(first) == render_markdown(second)
    assert report_json(first) == report_json(second)

    write_report(sweep, first)
    first_markdown = (sweep / config.REPORT_MARKDOWN).read_bytes()
    first_json = (sweep / config.REPORT_JSON).read_bytes()
    write_report(sweep)
    assert (sweep / config.REPORT_MARKDOWN).read_bytes() == first_markdown
    assert (sweep / config.REPORT_JSON).read_bytes() == first_json


def test_bench_report_never_compares_cohorts(tmp_path):
    production = full_cells("model-a")
    proxy = full_cells("proxy-c", cohort="proxy")
    for entry in proxy:
        entry["model"]["fidelity"] = "proxy"
    sweep = write_sweep(tmp_path, production + proxy)
    report = build_report(sweep)
    markdown = render_markdown(report)
    assert report["verdicts"] == [], "one model per cohort has no pair to compare"
    assert "Verdicts are computed **within a cohort**" in markdown
    assert "model-a" in markdown and "proxy-c" in markdown


def test_bench_report_marks_a_disabled_roster_entry(tmp_path):
    disabled = full_cells("opencode-deepseek", cohort="proxy", judge=None)
    for entry in disabled:
        entry["model"]["fidelity"] = "proxy"
    entries = full_cells("model-a") + disabled
    sweep = write_sweep(tmp_path, entries)
    report = build_report(sweep)
    markdown = render_markdown(report)
    assert any(
        model["key"] == "opencode-deepseek" and model["disabled"]
        for model in report["models"]
    )
    assert "opencode-deepseek | proxy | proxy | disabled — not scored" in markdown
    assert "Disabled roster entries" in markdown
    assert all(
        verdict.get("left") != "opencode-deepseek"
        and verdict.get("right") != "opencode-deepseek"
        for verdict in report["verdicts"]
    )


# ---------------------------------------------------------------------------
# Staleness and known recall gaps
# ---------------------------------------------------------------------------


def test_bench_report_refuses_scores_from_another_rubric(tmp_path):
    entries = full_cells("model-a")
    entries[0]["rubric_sha256"] = "0" * 64
    sweep = write_sweep(tmp_path, entries)

    try:
        build_report(sweep)
    except ValueError as exc:
        assert "stale" in str(exc)
        assert "rubric_sha256" in str(exc)
    else:  # pragma: no cover - the refusal is the contract
        raise AssertionError("a report must refuse scores from another rubric")


def test_bench_report_refuses_scores_from_another_plan(tmp_path):
    entries = full_cells("model-a")
    entries[0]["plan_hash"] = "another-plan"
    sweep = write_sweep(tmp_path, entries)

    with pytest.raises(ValueError, match="plan_hash"):
        build_report(sweep)


def test_bench_report_allow_stale_renders_a_banner(tmp_path):
    entries = full_cells("model-a")
    entries[0]["rubric_sha256"] = "0" * 64
    sweep = write_sweep(tmp_path, entries)

    report = build_report(sweep, allow_stale=True)
    markdown = render_markdown(report)

    assert report["stale"]
    assert "STALE SCORES — DO NOT QUOTE" in markdown
    assert markdown.index("STALE SCORES") < markdown.index("## 1. Header")


def test_bench_report_cli_exits_non_zero_on_stale_scores(tmp_path, capsys):
    from bench.cli import main

    entries = full_cells("model-a")
    entries[0]["rubric_sha256"] = "f" * 64
    sweep = write_sweep(tmp_path, entries)

    assert main(["report", str(sweep), "--quiet"]) == 2
    assert "stale" in capsys.readouterr().err
    assert main(["report", str(sweep), "--quiet", "--allow-stale"]) == 0


def test_bench_report_states_the_known_blocker_undercount(tmp_path):
    """A 0-blocker row must never read as proof of safety (rubric §12.4)."""
    entries = full_cells("model-a") + full_cells("model-b")
    sweep = write_sweep(tmp_path, entries)
    markdown = render_markdown(build_report(sweep))

    assert "Blocker recall is an undercount" in markdown
    assert "§12.4" in markdown
    for rule_id in ("X-01", "X-03", "R-05"):
        assert rule_id in markdown
    assert "A 0-blocker row means the checks found nothing" in markdown


def test_bench_report_refuses_a_plan_captured_under_another_rubric(tmp_path):
    """meta.json's rubric hash is part of the header, not decoration."""
    entries = full_cells("model-a")
    sweep = write_sweep(tmp_path, entries)
    meta = json.loads((sweep / config.META_FILENAME).read_text(encoding="utf-8"))
    meta["plan"]["rubric_hash"] = "0" * 64
    (sweep / config.META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="plan_rubric_hash"):
        build_report(sweep)
    assert build_report(sweep, allow_stale=True)["stale"]["plan_rubric_hash"]


def test_judged_half_is_withheld_above_the_unstable_cap(tmp_path):
    """§12.7 provisional certification: >15% unstable cells withholds J."""
    left = full_cells("model-a")
    right = full_cells("model-b")
    entries = left + right
    # 15 of 90 judged answers unstable = 16.7%, over the 15% cap.
    for entry in entries[:15]:
        entry["judge"] = None
        entry["judge_status"] = "judge-unstable"
        entry["judge_unstable"] = True
    sweep = write_sweep(tmp_path, entries)

    report = build_report(sweep)
    markdown = render_markdown(report)

    assert report["judge_withheld"] is True
    assert report["judge_unstable_rate"] > 0.15
    assert all(
        verdict["status"] == "insufficient_evidence"
        and "judge_withheld" in verdict["reasons"]
        for verdict in report["verdicts"]
    )
    assert "**J is withheld this sweep.**" in markdown
    assert "| model-a |" in markdown and "| withheld |" in markdown


def test_judged_half_is_published_below_the_unstable_cap(tmp_path):
    entries = full_cells("model-a") + full_cells("model-b")
    sweep = write_sweep(tmp_path, entries)

    report = build_report(sweep)

    assert report["judge_withheld"] is False


def test_blocker_grid_marks_reproducible_and_flaky_prompts(tmp_path):
    scenarios = ("healthy", "red_flags", "calibrating")
    prompts = ("this_week", "load_change", "intensity", "ready_10k", "review_4_weeks")
    entries = []
    for scenario in scenarios:
        for prompt in prompts:
            for repeat in range(3):
                blocked = 0
                if prompt == "load_change":
                    blocked = 1  # reproducible: every repeat
                elif prompt == "intensity" and repeat == 0:
                    blocked = 1  # flaky: one of three
                entries.append(
                    make_entry(
                        "model-a",
                        scenario,
                        prompt,
                        repeat=repeat,
                        blocker=blocked,
                    )
                )
    sweep = write_sweep(tmp_path, entries)

    report = build_report(sweep)
    model = report["models"][0]

    assert model["blocker_grid"]["healthy"]["load_change"] == [True, True, True]
    assert model["blocker_grid"]["healthy"]["intensity"] == [True, False, False]
    assert model["blocker_grid"]["red_flags"]["load_change"] == [True, True, True]
    assert model["blocker_grid"]["calibrating"]["intensity"] == [True, False, False]
    assert model["blocked_prompts_all_repeats"] == 1
    assert model["blocked_answers"] == 12  # 3 scenarios x (3 + 1)
    assert model["blocked_answers_total"] == 45

    markdown = render_markdown(report)
    assert "Read the grid, not the totals." in markdown
    assert "blocked prompts: 1/5 in every repeat" in markdown
    assert "| healthy | load_change | B | B | B |" in markdown
    assert "| healthy | intensity | B | . | . |" in markdown
    assert "All models — blocked answers: 12/45" in markdown


def test_blocker_grid_is_skipped_for_a_model_with_no_scored_records(tmp_path):
    entries = full_cells("model-a")
    unscored = make_entry("model-b", "healthy", "this_week")
    unscored["scored"] = False
    unscored["status"] = "timeout"
    unscored["judge"] = None
    sweep = write_sweep(tmp_path, entries + [unscored])

    report = build_report(sweep)
    model_b = next(model for model in report["models"] if model["key"] == "model-b")

    assert model_b["blocker_grid"] is None
    assert "**model-b** — blocked answers" not in render_markdown(report)
