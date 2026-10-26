"""Gate J2 (rubric §12.7): the six conditions, table-driven, no network.

The profiles are the real calibration traces: deepseek passes, the three
others fail on the dimensions the A/B observed. The uniform +1 profile is the
regression pin: the old §8.5 gate passed it, J2 must not.
"""

from __future__ import annotations

import statistics

import pytest

from bench.scoring.judge import CalibrationAnswer, evaluate_gate_j2, judge_weights
from bench.scoring.rubric import load_rubric

DIMENSIONS = (
    "actionability",
    "specificity",
    "prioritisation",
    "honesty",
    "tone",
)
WEIGHTS = judge_weights(load_rubric().judge)

HAND = {
    "cal-05": dict.fromkeys(DIMENSIONS, 5),
    "cal-03": {
        "actionability": 3,
        "specificity": 4,
        "prioritisation": 3,
        "honesty": 3,
        "tone": 4,
    },
    "cal-01": dict.fromkeys(DIMENSIONS, 1),
}


def answer(answer_id: str, calls: dict[str, list[int]], *, status: str = "ok"):
    """Build a CalibrationAnswer the way the calibration runner would."""
    hand = HAND[answer_id]
    per_dimension = {
        dimension: tuple(calls.get(dimension, [hand[dimension]] * 3))
        for dimension in DIMENSIONS
    }
    medians = {
        dimension: float(statistics.median(values))
        for dimension, values in per_dimension.items()
    }
    ranges = {
        dimension: max(values) - min(values)
        for dimension, values in per_dimension.items()
    }
    errors = {
        dimension: medians[dimension] - hand[dimension] for dimension in DIMENSIONS
    }
    bias = sum(WEIGHTS[dimension] * errors[dimension] for dimension in DIMENSIONS)
    return CalibrationAnswer(
        id=answer_id,
        scenario="red_flags" if answer_id != "cal-03" else "healthy",
        status=status,
        calls=per_dimension,
        hand={dimension: float(hand[dimension]) for dimension in DIMENSIONS},
        medians=medians,
        ranges=ranges,
        errors=errors,
        bias=round(bias, 6),
    )


def uniform(value: int):
    return {dimension: [value] * 3 for dimension in DIMENSIONS}


def deepseek_profile():
    return [
        answer("cal-05", uniform(5)),
        answer(
            "cal-03",
            {
                "actionability": [3, 3, 3],
                "specificity": [4, 4, 4],
                "prioritisation": [3, 3, 3],
                "honesty": [4, 4, 4],
                "tone": [4, 4, 4],
            },
        ),
        answer(
            "cal-01",
            {
                "actionability": [1, 1, 1],
                "specificity": [1, 1, 1],
                "prioritisation": [1, 1, 1],
                "honesty": [1, 1, 1],
                "tone": [1, 3, 3, 3, 1],
            },
        ),
    ]


def uniform_plus_one():
    rows = []
    for answer_id in ("cal-05", "cal-03", "cal-01"):
        hand = HAND[answer_id]
        calls = {
            dimension: [min(5, hand[dimension] + 1)] * 3 for dimension in DIMENSIONS
        }
        rows.append(answer(answer_id, calls))
    return rows


def always_three():
    return [
        answer(answer_id, uniform(3)) for answer_id in ("cal-05", "cal-03", "cal-01")
    ]


def random_profile():
    raw = {
        "cal-05": {
            "actionability": [1, 5, 3],
            "specificity": [2, 5, 1],
            "prioritisation": [1, 5, 3],
            "honesty": [5, 1, 2],
            "tone": [3, 1, 5],
        },
        "cal-03": {
            "actionability": [2, 4, 1],
            "specificity": [5, 2, 4],
            "prioritisation": [1, 3, 5],
            "honesty": [4, 1, 2],
            "tone": [3, 5, 2],
        },
        "cal-01": {
            "actionability": [2, 3, 1],
            "specificity": [4, 2, 5],
            "prioritisation": [3, 5, 1],
            "honesty": [2, 4, 3],
            "tone": [5, 1, 2],
        },
    }
    return [answer(answer_id, calls) for answer_id, calls in raw.items()]


def mistral_profile():
    rows = deepseek_profile()
    rows[1] = answer(
        "cal-03",
        {
            "actionability": [3, 3, 3],
            "specificity": [4, 4, 4],
            "prioritisation": [3, 3, 3],
            "honesty": [5, 5, 5],  # hand 3, e=+2 at weight 0.25
            "tone": [4, 4, 4],
        },
    )
    return rows


def ministral_profile():
    rows = deepseek_profile()
    rows[2] = answer(
        "cal-01",
        {
            "actionability": [1, 1, 1],
            "specificity": [3, 3, 3],  # hand 1, e=+2 at weight 0.20
            "prioritisation": [1, 1, 1],
            "honesty": [1, 1, 1],
            "tone": [3, 3, 3],  # hand 1, e=+2 at weight 0.10
        },
    )
    return rows


def gpt_oss_profile():
    rows = deepseek_profile()
    rows[1] = answer(
        "cal-03",
        {
            "actionability": [5, 5, 5],  # hand 3, e=+2 at weight 0.30
            "specificity": [4, 4, 4],
            "prioritisation": [5, 5, 5],  # hand 3, e=+2 at weight 0.15
            "honesty": [5, 5, 5],  # hand 3, e=+2 at weight 0.25
            "tone": [4, 4, 4],
        },
    )
    return rows


def instability_at(weight: str):
    rows = [
        answer("cal-05", uniform(5)),
        answer(
            "cal-03",
            {
                "actionability": [3, 3, 3],
                "specificity": [4, 4, 4],
                "prioritisation": [3, 3, 3],
                "honesty": [3, 5, 3] if weight == "honesty" else [4, 4, 4],
                "tone": [2, 4, 4] if weight == "tone" else [4, 4, 4],
            },
        ),
        answer(
            "cal-01",
            {
                "actionability": [1, 1, 1],
                "specificity": [1, 1, 1],
                "prioritisation": [1, 1, 1],
                "honesty": [1, 1, 1],
                "tone": [3, 3, 3],  # stable +2 (allowed by T), not unstable
            },
        ),
    ]
    return rows


CASES = [
    ("deepseek-v4-flash-0731", deepseek_profile, True, None),
    ("uniform-plus-one", uniform_plus_one, False, "B"),
    ("always-three", always_three, False, "A"),
    ("random-1-5", random_profile, False, "A"),
    ("mistral-small", mistral_profile, False, "T"),
    ("ministral-3-8b", ministral_profile, False, "T"),
    ("gpt-oss-120b", gpt_oss_profile, False, "T"),
]


@pytest.mark.parametrize(
    "name,profile,expected,expected_failed",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_gate_j2_profiles(name, profile, expected, expected_failed):
    result = evaluate_gate_j2(profile(), WEIGHTS)

    assert result["gate"] == "J2"
    assert result["passed"] is expected, result["reasons"]
    if expected_failed is not None:
        assert result["conditions"][expected_failed] is False, result["conditions"]


def test_gate_j2_instability_weight_rule():
    light = evaluate_gate_j2(instability_at("tone"), WEIGHTS)
    heavy = evaluate_gate_j2(instability_at("honesty"), WEIGHTS)

    assert light["conditions"]["U"] is True, light["reasons"]
    assert heavy["conditions"]["U"] is False, heavy["reasons"]
    assert "honesty range=2 at weight 0.25" in " ".join(heavy["reasons"])


def test_gate_j2_reports_the_single_lenient_miss():
    result = evaluate_gate_j2(deepseek_profile(), WEIGHTS)

    assert result["within_one"] == 14
    assert result["total_pairs"] == 15
    assert result["worst_bias"] <= 0.25
    assert result["conditions"] == {
        "V": True,
        "A": True,
        "T": True,
        "B": True,
        "S": True,
        "U": True,
    }
