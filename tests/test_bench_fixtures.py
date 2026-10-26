"""Frozen fixture invariants and the prompt guard."""

from __future__ import annotations

import json
import re

from bench import config
from bench.fixtures import load_fixtures, load_prompts, scenarios, verify_frozen

APP_JS = config.REPO_ROOT / "app" / "static" / "app.js"


def test_bench_fixture_invariants():
    assert verify_frozen() == []

    for fixture in load_fixtures():
        assert fixture.version == config.FIXTURE_VERSION
        assert fixture.as_of
        assert fixture.snapshot["load"]["last_7d"] is not None
        assert fixture.tool_context["today"] == fixture.as_of
        assert fixture.tool_context["activities"]


def test_bench_fixture_meta_is_frozen_and_hashed():
    for name in scenarios.SCENARIOS:
        path = config.SNAPSHOTS_DIR / f"{name}.v{config.FIXTURE_VERSION}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        meta = document["meta"]
        assert meta["scenario"] == name
        assert meta["version"] == config.FIXTURE_VERSION
        assert meta["as_of"]
        assert meta["generated_at"]
        assert len(meta["generator_sha256"]) == 64
        assert len(meta["snapshot_sha256"]) == 64
        assert len(meta["tool_context_sha256"]) == 64


def test_bench_red_flags_fixture_keeps_its_trap():
    fixture = load_fixtures(["red_flags"])[0]
    snapshot = fixture.snapshot
    assert snapshot["load_change"]["ratio"] > 1.5
    assert snapshot["load_change"]["band"] == "sharp_increase"
    assert (snapshot["load"]["last_7d"] / snapshot["load"]["prev_7d"] - 1) > 0.30
    assert any(episode["active"] for episode in snapshot["injuries"]["episodes"])
    assert any(flag["level"] == "warn" for flag in snapshot["red_flags"])


def test_bench_prompts_match_the_ui():
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"const COACH_SUGGESTIONS = \[(.*?)\];", source, re.S)
    assert match, "COACH_SUGGESTIONS not found in app.js"
    ui_prompts = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))
    frozen = [prompt.text for prompt in load_prompts()]

    assert frozen == ui_prompts
