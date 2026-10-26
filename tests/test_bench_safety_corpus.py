"""The safety acceptance corpus for X-01, X-03 and R-05.

The corpus is the contract: one answer, one frozen scenario, the rubric's
expected outcome per rule. Adding a safety phrase means adding a case, not
widening a regex window. The text is synthetic advice only — no athlete data
and no keys — and two ambiguous cases record the conservative direction the
implementation chose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bench.fixtures import load_fixtures
from bench.scoring.rubric import apply_rubric, load_rubric

CORPUS_PATH = Path(__file__).parent / "fixtures" / "safety_corpus.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
CASES = CORPUS["cases"]
FIXTURES = {fixture.scenario: fixture for fixture in load_fixtures()}
RUBRIC = load_rubric()

_ACTUAL = {"pass": "pass", "fail": "fail", "skip": "skip"}


def _record(case: dict) -> dict:
    fixture = FIXTURES[case["scenario"]]
    return {
        "schema_version": 1,
        "record_id": f"corpus-{case['id']}",
        "sweep": "corpus",
        "plan_hash": "corpus",
        "status": "ok",
        "answer": case["answer"],
        "answer_sha256": "0" * 64,
        "model": {"key": "corpus", "cohort": "production", "fidelity": "production"},
        "fixture": {"scenario": case["scenario"], "version": fixture.version},
        "prompt": {"id": "this_week"},
        "repeat": 0,
        "finish_reason": "stop",
        "context": {"chars": 8000, "truncated": False},
        "tool_calls": [],
    }


def _verdict(outcome) -> str:
    if not outcome.applies:
        return "skip"
    return "pass" if outcome.passed else "fail"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_safety_corpus(case):
    outcomes = {
        outcome.rule_id: outcome
        for outcome in apply_rubric(_record(case), FIXTURES[case["scenario"]], RUBRIC)
    }

    wrong = []
    for rule_id, expected in case["expect"].items():
        outcome = outcomes[rule_id]
        actual = _verdict(outcome)
        if actual != expected:
            wrong.append(
                f"{rule_id}: expected {expected}, got {actual} "
                f"({outcome.detail}; {outcome.evidence})"
            )
    assert not wrong, f"{case['id']}: " + " | ".join(wrong)


def test_safety_corpus_covers_every_rule_and_is_synthetic():
    assert len(CASES) >= 25
    covered = {rule for case in CASES for rule in case["expect"]}
    assert covered == {"X-01", "X-03", "R-05"}
    assert {case["scenario"] for case in CASES} <= set(FIXTURES)
    for case in CASES:
        assert set(case["expect"]) == covered
        assert not re.search(r"sk-[A-Za-z0-9]|[0-9a-f]{32,}|\b\d{6,}\b", case["answer"])
