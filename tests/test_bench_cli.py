"""CLI contracts: fixtures, availability and a network-free dry run."""

from __future__ import annotations

import json

from bench import cli, config
from bench.providers.base import AvailabilityStatus
from bench.providers.fake import FakeProvider
from bench.providers.openai_http import OpenAIHTTPProvider
from bench.roster import availability_for, load_roster
from tests.bench_helpers import make_completion, make_plan, make_spec


def test_bench_cli_fixtures_check(capsys):
    assert cli.main(["fixtures", "--check"]) == 0
    captured = capsys.readouterr()
    assert "fixtures ok" in captured.out
    assert "5 prompts" in captured.out


def test_bench_cli_dry_run_does_not_call_a_provider(tmp_path, monkeypatch, capsys):
    def explode(self, request):
        raise AssertionError("dry run must not call a provider")

    monkeypatch.setattr(OpenAIHTTPProvider, "complete", explode)

    code = cli.main(
        [
            "capture",
            "--models",
            "ollama-local",
            "--scenarios",
            "healthy",
            "--prompts",
            "this_week",
            "--repeats",
            "1",
            "--root",
            str(tmp_path),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "planned calls: 1" in captured.out
    assert "dry run: no network calls made" in captured.out
    assert not (tmp_path / "sweeps").exists()


def test_bench_cli_refuses_a_different_plan_hash(tmp_path, capsys):
    sweep_dir = tmp_path / config.SWEEPS_DIRNAME / config.DEFAULT_SWEEP
    sweep_dir.mkdir(parents=True)
    (sweep_dir / config.META_FILENAME).write_text(
        json.dumps({"plan": {"plan_hash": "a-different-plan"}}), encoding="utf-8"
    )

    code = cli.main(
        [
            "capture",
            "--models",
            "ollama-local",
            "--scenarios",
            "healthy",
            "--prompts",
            "this_week",
            "--repeats",
            "1",
            "--root",
            str(tmp_path),
        ]
    )

    assert code == 2
    assert "refusing to reuse sweep" in capsys.readouterr().err
    assert not (sweep_dir / config.RECORDS_FILENAME).exists()


def test_bench_cli_capture_writes_records_and_meta(tmp_path, monkeypatch, capsys):
    roster_path = tmp_path / "roster.json"
    roster_path.write_text(
        json.dumps(
            {
                "prices_as_of": "2026-01-01",
                "models": [
                    {
                        "key": "fake-1",
                        "adapter": "fake",
                        "origin": "test",
                        "model": "fake-model",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = FakeProvider()
    monkeypatch.setattr(cli, "ADAPTERS", {"fake": provider})
    monkeypatch.setattr(cli, "_git_sha", lambda: "test-sha")

    code = cli.main(
        [
            "capture",
            "--roster",
            str(roster_path),
            "--models",
            "all",
            "--scenarios",
            "healthy",
            "--prompts",
            "this_week",
            "--repeats",
            "1",
            "--sweep",
            "unit",
            "--root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    sweep_dir = tmp_path / config.SWEEPS_DIRNAME / "unit"
    records = [
        json.loads(line)
        for line in (sweep_dir / config.RECORDS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    meta = json.loads((sweep_dir / config.META_FILENAME).read_text(encoding="utf-8"))

    assert code == 0
    assert len(provider.requests) == 1
    assert len(records) == 1
    assert records[0]["status"] == "ok"
    assert "ok 1/1" in output
    assert meta["git_sha"] == "test-sha"
    assert meta["plan"]["plan_hash"] == records[0]["plan_hash"]
    assert meta["counts"]["ok"] == 1


def test_roster_distinguishes_missing_key_from_unknown_id(monkeypatch):
    from app import coach_llm

    monkeypatch.delenv("ALBERT_API_KEY", raising=False)
    albert_entry = coach_llm.find_model("albert-qwen")
    assert albert_entry is not None
    monkeypatch.setitem(albert_entry, "api_key", "")
    roster = load_roster()
    albert = roster.by_key()["albert-qwen"]
    assert availability_for(albert).status == AvailabilityStatus.MISSING_KEY

    unknown = make_spec(
        "unknown", adapter="openai_http", registry_id="not-in-models-json"
    )
    assert availability_for(unknown).status == AvailabilityStatus.UNKNOWN_ID


def test_roster_params_are_the_production_values():
    from app import coach_llm

    roster = load_roster()
    gemma = roster.by_key()["gemma-4-31b"]
    registry = coach_llm.find_model("gemma-4-31b")

    assert gemma.params["temperature"] == registry["temperature"]
    assert gemma.params["max_tokens"] == registry["max_tokens"]
    assert gemma.params["tools"] == len(coach_llm.coach_tools.TOOL_SCHEMAS)
    assert gemma.cohort == "production"


def test_roster_selects_all_and_named_models():
    from bench.roster import select_specs

    roster = load_roster()
    assert select_specs(roster, ["all"]) == list(roster.specs)
    selected = select_specs(roster, ["gemma-4-31b,ollama-local"])
    assert [spec.key for spec in selected] == ["gemma-4-31b", "ollama-local"]


# ---------------------------------------------------------------------------
# Comparability: the plan hash covers the rubric and the judge
# ---------------------------------------------------------------------------

RUBRIC_RULES = [
    {
        "id": "S-01",
        "severity": "minor",
        "check": "required_sections",
        "applies_to": {"scenarios": ["*"], "prompts": ["*"]},
        "params": {"min_words": 1},
    }
]


def _roster(tmp_path):
    path = tmp_path / "roster.json"
    path.write_text(
        json.dumps(
            {
                "prices_as_of": "2026-01-01",
                "models": [
                    {
                        "key": "fake-1",
                        "adapter": "fake",
                        "origin": "test",
                        "model": "fake-model",
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _rubric(tmp_path, name: str, version: str):
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "source": "test",
                "constants": [],
                "judge": {},
                "rules": RUBRIC_RULES,
            }
        ),
        encoding="utf-8",
    )
    return path


def _capture_args(root, roster, sweep, *extra):
    return [
        "capture",
        "--roster",
        str(roster),
        "--models",
        "all",
        "--scenarios",
        "healthy",
        "--prompts",
        "this_week",
        "--repeats",
        "1",
        "--root",
        str(root),
        "--sweep",
        sweep,
        *extra,
    ]


def _meta(path):
    return json.loads((path / config.META_FILENAME).read_text(encoding="utf-8"))


def _records(path):
    return [
        json.loads(line)
        for line in (path / config.RECORDS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def test_bench_capture_plan_hash_covers_the_rubric_and_the_judge(tmp_path, monkeypatch):
    """Changing the rubric or the judge must make a different measurement."""
    import hashlib

    monkeypatch.setattr(cli, "ADAPTERS", {"fake": FakeProvider()})
    monkeypatch.setattr(cli, "_git_sha", lambda: "test-sha")
    roster = _roster(tmp_path)
    rubric_a = _rubric(tmp_path, "rubric-a", "a")
    rubric_b = _rubric(tmp_path, "rubric-b", "b")

    assert (
        cli.main(_capture_args(tmp_path, roster, "a", "--rubric", str(rubric_a))) == 0
    )
    assert (
        cli.main(
            _capture_args(
                tmp_path,
                roster,
                "b",
                "--rubric",
                str(rubric_b),
                "--judge-model",
                "judge-x",
            )
        )
        == 0
    )
    assert (
        cli.main(
            _capture_args(
                tmp_path,
                roster,
                "c",
                "--rubric",
                str(rubric_a),
                "--judge-model",
                "judge-y",
            )
        )
        == 0
    )

    root = tmp_path / config.SWEEPS_DIRNAME
    meta_a, meta_b, meta_c = _meta(root / "a"), _meta(root / "b"), _meta(root / "c")

    for meta in (meta_a, meta_b, meta_c):
        assert meta["rubric"] is not None
        assert meta["rubric"]["sha256"] == meta["plan"]["rubric_hash"]
        assert meta["rubric"]["text"].strip().startswith("{")
        assert meta["plan"]["judge_model"] == meta["judge_model"]
        assert meta["system_prompt"]["sha256"]
        assert all(prompt["sha256"] for prompt in meta["prompts"])

    assert (
        meta_a["plan"]["rubric_hash"]
        == hashlib.sha256(rubric_a.read_bytes()).hexdigest()
    )
    assert meta_a["judge_model"] is None
    assert meta_b["judge_model"] == "judge-x"

    hashes = {
        meta_a["plan"]["plan_hash"],
        meta_b["plan"]["plan_hash"],
        meta_c["plan"]["plan_hash"],
    }
    assert len(hashes) == 3, "a rubric or judge change must change the plan hash"
    assert _records(root / "a")[0]["plan_hash"] == meta_a["plan"]["plan_hash"]


def test_bench_capture_force_archives_records_from_an_older_plan(
    tmp_path, monkeypatch, capsys
):
    """--force replaces the sweep; it must never append to another plan."""
    monkeypatch.setattr(cli, "ADAPTERS", {"fake": FakeProvider()})
    monkeypatch.setattr(cli, "_git_sha", lambda: "test-sha")
    roster = _roster(tmp_path)
    rubric_a = _rubric(tmp_path, "rubric-a", "a")
    rubric_b = _rubric(tmp_path, "rubric-b", "b")
    sweep_dir = tmp_path / config.SWEEPS_DIRNAME / "unit"

    assert (
        cli.main(_capture_args(tmp_path, roster, "unit", "--rubric", str(rubric_a)))
        == 0
    )
    old_hash = _meta(sweep_dir)["plan"]["plan_hash"]

    # Without --force the different plan is refused, not merged.
    code = cli.main(_capture_args(tmp_path, roster, "unit", "--rubric", str(rubric_b)))
    assert code == 2
    assert "refusing to reuse sweep" in capsys.readouterr().err
    assert len(_records(sweep_dir)) == 1

    assert (
        cli.main(
            _capture_args(
                tmp_path, roster, "unit", "--rubric", str(rubric_b), "--force"
            )
        )
        == 0
    )
    new_hash = _meta(sweep_dir)["plan"]["plan_hash"]
    assert new_hash != old_hash

    rows = _records(sweep_dir)
    assert len(rows) == 1
    assert {row["plan_hash"] for row in rows} == {new_hash}

    backup = sweep_dir / f"records.{old_hash}.jsonl.bak"
    assert backup.exists()
    assert (
        json.loads(backup.read_text(encoding="utf-8").splitlines()[0])["plan_hash"]
        == old_hash
    )


# ---------------------------------------------------------------------------
# score refuses to mix or to re-label another measurement
# ---------------------------------------------------------------------------


def _score_record(record_id, plan_hash, *, scenario="healthy", prompt="this_week"):
    from bench.fixtures import load_fixtures

    fixture = {item.scenario: item for item in load_fixtures()}[scenario]
    return {
        "schema_version": config.BENCH_SCHEMA_VERSION,
        "record_id": record_id,
        "sweep": "unit",
        "plan_hash": plan_hash,
        "status": "ok",
        "answer": "Your load is 580.0 units.",
        "answer_sha256": "sha-" + record_id,
        "model": {"key": "model-a", "cohort": "production", "fidelity": "production"},
        "fixture": {
            "scenario": scenario,
            "version": fixture.version,
            "snapshot_sha256": fixture.snapshot_sha256,
            "tool_context_sha256": fixture.tool_context_sha256,
        },
        "prompt": {"id": prompt},
        "repeat": 0,
        "finish_reason": "stop",
        "tool_calls": [],
    }


def _write_records(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_bench_score_refuses_records_from_two_plans(tmp_path, capsys):
    _write_records(
        tmp_path / config.RECORDS_FILENAME,
        [_score_record("rec-1", "plan-a"), _score_record("rec-2", "plan-b")],
    )

    assert cli.main(["score", str(tmp_path), "--quiet"]) == 2
    assert "mixes plan hashes" in capsys.readouterr().err
    assert not (tmp_path / config.SCORES_FILENAME).exists()


def test_bench_score_refuses_a_rubric_that_moved(tmp_path, capsys):
    _write_records(
        tmp_path / config.RECORDS_FILENAME, [_score_record("rec-1", "plan-a")]
    )
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {"plan_hash": "plan-a", "rubric_hash": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["score", str(tmp_path), "--quiet"]) == 2
    assert "rubric" in capsys.readouterr().err

    assert cli.main(["score", str(tmp_path), "--quiet", "--allow-stale"]) == 0
    assert (tmp_path / config.SCORES_FILENAME).exists()


def test_bench_score_rejects_a_foreign_tool_context(tmp_path):
    row = _score_record("rec-1", "plan-a")
    row["fixture"]["tool_context_sha256"] = "0" * 64
    _write_records(tmp_path / config.RECORDS_FILENAME, [row])

    assert cli.main(["score", str(tmp_path), "--quiet"]) == 2


# ---------------------------------------------------------------------------
# Pacing in the dry run and in the capture summary
# ---------------------------------------------------------------------------


def test_bench_dry_run_counts_pacing_in_the_wall_clock(capsys):
    from bench.cli import _print_dry_run
    from bench.providers.base import Availability

    spec = make_spec(
        "albert-qwen", adapter="openai_http", origin="albert", model="provider-model"
    )
    plan = make_plan(models=[spec])
    availability = {spec.key: Availability(AvailabilityStatus.OK)}

    _print_dry_run(plan, availability, {}, False)

    output = capsys.readouterr().out
    assert "3.75 s between requests" in output
    assert "128,000 input tokens/min" in output
    assert "50 req/min" in output
    assert "estimated pacing floor: 4s" in output


def test_bench_cli_capture_prints_retries_per_model(tmp_path, monkeypatch, capsys):
    roster_path = _roster(tmp_path)
    completion = make_completion(
        diagnostics={
            "attempts": 3,
            "retried": True,
            "retry_reasons": ["429", "429"],
            "retry_wait_ms": 7000,
            "rate_limit_wait_ms": 7000,
        }
    )
    monkeypatch.setattr(cli, "ADAPTERS", {"fake": FakeProvider(default=completion)})
    monkeypatch.setattr(cli, "_git_sha", lambda: "test-sha")

    code = cli.main(_capture_args(tmp_path, roster_path, "retries", "--quiet"))

    assert code == 0
    # ``--quiet`` silences per-call progress, not the summary.
    output = capsys.readouterr().out
    assert "retries: fake-1 1" in output
    assert "429 x2" in output
    assert "rate-limit wait: 7.0 s" in output
    meta = _meta(tmp_path / config.SWEEPS_DIRNAME / "retries")
    assert meta["counts"]["retries_by_model"] == {"fake-1": 1}
    assert meta["counts"]["rate_limit_wait_s"] == 7.0
