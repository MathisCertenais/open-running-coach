"""Wilson interval and exact sign test, pinned to the rubric's own numbers."""

from __future__ import annotations

import pytest

from bench.scoring import stats


def test_bench_wilson_and_sign_test():
    """Rubric §9.2 condition 3: 12/15 -> 0.035, 11/15 -> 0.118."""
    assert stats.sign_test(12, 3) == pytest.approx(0.035156, abs=1e-6)
    assert stats.sign_test(11, 4) == pytest.approx(0.118469, abs=1e-6)
    assert stats.sign_test(15, 0) == pytest.approx(2 / 32768, abs=1e-8)
    assert stats.sign_test(0, 0) == 1.0
    assert stats.sign_test(8, 7) == 1.0

    low, high = stats.wilson_interval(0, 15)
    assert low == 0.0
    assert 0.0 < high < 0.25

    low, high = stats.wilson_interval(15, 15)
    assert high == 1.0
    assert low > 0.75

    low, high = stats.wilson_interval(1, 15)
    assert 0.0 < low < 1 / 15 < high < 0.35

    assert stats.wilson_interval(0, 0) == (0.0, 1.0)


def test_bench_wilson_contains_the_proportion():
    for successes in range(0, 16):
        low, high = stats.wilson_interval(successes, 15)
        assert 0.0 <= low <= successes / 15 <= high <= 1.0


def test_bench_sign_test_threshold():
    assert stats.sign_test_threshold(15) == 12
    # A smaller design cannot be declared better on a looser bar.
    assert stats.sign_test_threshold(10) == 9
    # With four cells even 4/4 is p = 0.125: no bar can be reached.
    assert stats.sign_test_threshold(4) == 5


def test_bench_descriptive_statistics():
    assert stats.median([1, 2, 3]) == 2
    assert stats.median([1, 2, 3, 4]) == 2.5
    assert stats.median([]) is None
    assert stats.iqr([1, 2, 3, 4, 5]) == (2.0, 4.0)
    assert stats.mean([2, 4]) == 3
    assert stats.stdev([2, 4]) == pytest.approx(1.41421356)
    assert stats.stdev([2]) is None
