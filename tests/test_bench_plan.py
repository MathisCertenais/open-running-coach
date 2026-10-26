"""Plan determinism and sweep comparability."""

from __future__ import annotations

from bench.plan import build_plan
from tests.bench_helpers import (
    make_fixture,
    make_plan,
    make_prompt,
    make_spec,
)


def test_bench_plan_deterministic_ids():
    models = [make_spec("a"), make_spec("b")]
    fixtures = [make_fixture("healthy"), make_fixture("red_flags")]
    prompts = [make_prompt("this_week"), make_prompt("load_change")]

    first = build_plan(models, [f.ref() for f in fixtures], prompts, 2, 0)
    second = build_plan(models, [f.ref() for f in fixtures], prompts, 2, 0)

    assert len(first.items) == 2 * 2 * 2 * 2
    assert [item.id for item in first.items] == [item.id for item in second.items]
    assert len({item.id for item in first.items}) == len(first.items)

    order = [
        (item.model.key, item.repeat, item.fixture.scenario, item.prompt.id)
        for item in first.items
    ]
    assert order[:4] == [
        ("a", 0, "healthy", "this_week"),
        ("a", 0, "healthy", "load_change"),
        ("a", 0, "red_flags", "this_week"),
        ("a", 0, "red_flags", "load_change"),
    ]
    assert order[4][0:2] == ("a", 1)
    assert order[8][0:2] == ("b", 0)


def test_bench_plan_hash_changes_with_any_input():
    base = make_plan()
    assert base.plan_hash

    more_repeats = make_plan(repeats=2)
    assert more_repeats.plan_hash != base.plan_hash

    other_prompt = make_plan(prompts=[make_prompt("this_week", "Different?")])
    assert other_prompt.plan_hash != base.plan_hash

    other_fixture = make_plan(
        fixtures=[make_fixture("red_flags", snapshot={"load": {"last_7d": 1}})]
    )
    assert other_fixture.plan_hash != base.plan_hash

    other_params = make_plan(models=[make_spec(params={"temperature": 0.9})])
    assert other_params.plan_hash != base.plan_hash


def test_bench_plan_hash_ignores_a_price_update():
    from bench.providers.base import Pricing

    base = make_plan(models=[make_spec(pricing=Pricing(1.0, 2.0))])
    changed = make_plan(models=[make_spec(pricing=Pricing(3.0, 4.0))])

    # A price change alters the cost report, not the answer comparability.
    assert base.plan_hash == changed.plan_hash


def test_bench_plan_hash_ignores_nothing_silently_change_of_registry():
    base = make_plan(models=[make_spec(registry_id="gemma-4-31b")])
    changed = make_plan(models=[make_spec(registry_id="ollama-local")])
    assert base.plan_hash != changed.plan_hash
