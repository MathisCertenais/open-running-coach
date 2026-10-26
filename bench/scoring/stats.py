"""Interval and hypothesis-test arithmetic for the rubric's verdict.

Everything here is plain ``math`` so a verdict can be recomputed offline from
``scores.jsonl`` years later, with no dependency and no scipy. The expected
values are pinned by the rubric's own examples: 12/15 -> p = 0.035 and 11/15 ->
p = 0.118 (two-sided exact binomial).
"""

from __future__ import annotations

import math
from typing import Sequence


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean, or ``None`` for an empty sample."""
    return sum(values) / len(values) if values else None


def stdev(values: Sequence[float]) -> float | None:
    """Sample standard deviation (n-1), or ``None`` when n < 2.

    The report describes a sample of answers, not a population, so the sample
    form is the one that belongs in a table next to a mean.
    """
    if len(values) < 2:
        return None
    centre = sum(values) / len(values)
    variance = sum((value - centre) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Linear-interpolation percentile, the convention spreadsheets use."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def median(values: Sequence[float]) -> float | None:
    """Median, or ``None`` for an empty sample."""
    return percentile(values, 0.5)


def iqr(values: Sequence[float]) -> tuple[float, float] | None:
    """Interquartile range as ``(q1, q3)``, or ``None`` for an empty sample."""
    if not values:
        return None
    return (percentile(values, 0.25), percentile(values, 0.75))


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation because blocker rates are often 0
    or near it, where the normal interval collapses to a point and would make
    two perfect records look "non-overlapping" (rubric §9.2 condition 1).
    ``total == 0`` returns the whole unit interval: no observation, no claim.
    """
    if total <= 0:
        return (0.0, 1.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided binomial p-value for a paired sign test at p = 0.5.

    Ties are not passed in: a tie carries no direction, so it is excluded from
    n rather than counted as half a win (rubric §9.2 condition 3 speaks of
    cells that "favour" a model).
    """
    n = wins + losses
    if n <= 0:
        return 1.0
    extreme = max(wins, losses)
    tail = sum(math.comb(n, index) for index in range(extreme, n + 1)) / 2**n
    return min(1.0, 2 * tail)


def sign_test_threshold(cells: int) -> int:
    """Wins needed for the sign test to reach p < 0.05 at the rubric's n.

    At n = 15 the rubric fixes the bar at 12 of 15 (p = 0.035). For another n
    the smallest count whose one-sided upper tail is below 0.025 — equivalently
    a two-sided p below 0.05 — is used, so a sweep with fewer cells cannot be
    declared better on a looser bar.
    """
    if cells <= 0:
        return 1
    for wins in range(0, cells + 1):
        tail = (
            sum(math.comb(cells, index) for index in range(wins, cells + 1)) / 2**cells
        )
        if tail < 0.025:
            return wins
    return cells + 1
