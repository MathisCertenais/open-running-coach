"""Blind judge: independence, schema, repeats, instability and calibration.

No network: every case uses ``FakeJudgeClient``. The three calibration answers
are the scientist's hand-scored set from rubric §12.5.4, loaded from the frozen
fixture; the fake scoreboard is built from their hand scores, so the gate is
tested against the real expectations.
"""

from __future__ import annotations

import json

import pytest

from bench import config
from bench.fixtures import load_fixtures
from bench.scoring import judge as judge_module
from bench.scoring.judge import (
    DIMENSIONS,
    build_payload,
    judge_answer,
    load_calibration,
    parse_reply,
    refuse_self_judging,
    run_calibration,
)
from bench.scoring.judge_client import FakeJudgeClient, JudgeReply
from bench.scoring.rubric import load_rubric
from tests.bench_helpers import make_spec

FIXTURES = {fixture.scenario: fixture for fixture in load_fixtures()}
RUBRIC = load_rubric()
JUDGE = RUBRIC.judge
ANSWER = "Your load rose to 137.1 from 85.7, a sharp increase. The knee is the limiting factor."
PROMPT = "Why did my load change?"


def make_record(
    *,
    answer: str = ANSWER,
    scenario: str = "red_flags",
    prompt: str = "load_change",
    model_key: str = "secret-model",
    record_id: str = "rec-1",
    repeat: int = 0,
) -> dict:
    return {
        "record_id": record_id,
        "plan_hash": "plan-hash",
        "status": "ok",
        "answer": answer,
        "model": {
            "key": model_key,
            "adapter": "fake",
            "origin": "test",
            "model_id": "provider-model-id",
            "cohort": "production",
        },
        "fixture": {"scenario": scenario, "version": 1},
        "prompt": {"id": prompt},
        "repeat": repeat,
        "finish_reason": "stop",
        "tool_calls": [],
        "outcomes": [{"rule_id": "L-02", "passed": False, "evidence": "hidden"}],
    }


def make_reply(
    answer: str,
    scores: dict[str, int],
    *,
    rationale: str = "The answer is clear and usable.",
    quote: str | None = None,
) -> str:
    quoted = quote or answer[:40]
    payload = {
        "scores": {dimension: scores[dimension] for dimension in DIMENSIONS},
        "rationale": {dimension: rationale for dimension in DIMENSIONS},
        "quotes": {"strongest": quoted, "weakest": quoted},
        "confidence": "high",
    }
    return json.dumps(payload)


def uniform(score: int) -> dict[str, int]:
    return {dimension: score for dimension in DIMENSIONS}


def test_bench_judge_never_judges_itself():
    with pytest.raises(ValueError, match="model under test"):
        refuse_self_judging(
            ["gpt-oss-120b", "gpt-oss-120b"],
            [make_spec("judge", model="gpt-oss-120b")],
        )
    # A different id is allowed.
    refuse_self_judging(["judge-model"], [make_spec("candidate", model="other")])


def test_bench_judge_invalid_json_is_unknown():
    client = FakeJudgeClient(["not json", "still not json"])
    cell = judge_answer(make_record(), FIXTURES["red_flags"], PROMPT, client, JUDGE)
    assert cell.status == "judge-invalid"
    assert cell.dimensions is None, "no imputed score"
    assert cell.calls == 2, "one call and one retry, then stop"
    assert "no JSON object" in cell.detail


def test_bench_judge_median_of_three():
    replies = [
        make_reply(ANSWER, uniform(3)),
        make_reply(ANSWER, uniform(4)),
        make_reply(ANSWER, uniform(3)),
    ]
    cell = judge_answer(
        make_record(), FIXTURES["red_flags"], PROMPT, FakeJudgeClient(replies), JUDGE
    )
    assert cell.status == "ok"
    assert cell.calls == 3
    assert all(cell.dimensions[dimension] == 3.0 for dimension in DIMENSIONS)


def test_bench_judge_unstable_cell_excluded():
    def spread():
        # actionability 1, 3, 5 -> span 4; a fourth 1 leaves it unstable.
        scores = uniform(3)
        scores["actionability"] = 1
        return make_reply(ANSWER, scores, rationale="The answer says your load rose.")

    def spread_high():
        scores = uniform(3)
        scores["actionability"] = 5
        return make_reply(
            ANSWER,
            scores,
            rationale="The answer says your load rose, so it is actionable.",
        )

    replies = [
        spread(),
        make_reply(ANSWER, uniform(3)),
        spread_high(),
        spread(),
    ]
    cell = judge_answer(
        make_record(), FIXTURES["red_flags"], PROMPT, FakeJudgeClient(replies), JUDGE
    )
    assert cell.status == "judge-unstable"
    assert cell.dimensions is None
    assert cell.calls == 4
    assert "actionability" in cell.unstable_dimensions


def test_bench_judge_payload_is_blind():
    record = make_record()
    payload = build_payload(record, FIXTURES["red_flags"], PROMPT, [])
    assert set(payload) == {
        "athlete_data",
        "tool_results",
        "question",
        "answer",
        "truncated",
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "secret-model",
        "provider-model-id",
        "plan-hash",
        "rec-1",
        "outcomes",
        "L-02",
        "coverage",
        "gate",
    ):
        assert forbidden not in rendered
    # The inner snapshot is allowed; the file's meta block is not.
    assert payload["athlete_data"] == FIXTURES["red_flags"].snapshot
    assert "scenario" not in payload["athlete_data"]
    assert "snapshot_sha256" not in payload["athlete_data"]


def test_bench_judge_accepts_prose_and_fences_but_validates_the_schema():
    good = make_reply(ANSWER, uniform(3))
    assert parse_reply(good, ANSWER)[0] is not None
    # The real judge wrapped its JSON in commentary; extraction accepts it.
    assert parse_reply("Here you go: " + good, ANSWER)[0] is not None
    assert parse_reply("```json\n" + good + "\n```", ANSWER)[0] is not None
    payload = json.loads(good)
    payload["quotes"]["strongest"] = "not in the answer"
    assert parse_reply(json.dumps(payload), ANSWER)[0] is None
    payload = json.loads(good)
    payload["scores"]["tone"] = True
    assert parse_reply(json.dumps(payload), ANSWER)[0] is None


def _calibration_replies(expected_by_answer: dict[str, dict[str, int]]):
    def reply(_system: str, user: str) -> str:
        payload = json.loads(user)
        answer = payload["answer"]
        expected = expected_by_answer[answer]
        rationale = (
            "The answer names the knee, the limiting constraint, and a tempo plan."
            if max(expected.values()) == 5
            else "The answer mentions readiness and runs, but gives no recommendation."
            if max(expected.values()) == 1
            else "The answer is clear and usable."
        )
        return make_reply(answer, expected, rationale=rationale)

    return reply


def test_bench_judge_calibration_gate():
    document = load_calibration()
    expected = {
        answer["answer"]: {
            dimension: int(answer["expected"][dimension]) for dimension in DIMENSIONS
        }
        for answer in document["answers"]
    }
    calibrated = FakeJudgeClient([_calibration_replies(expected)] * 9)
    result = run_calibration(calibrated, JUDGE, FIXTURES)
    assert result.passed is True, result.details
    assert result.prompt_sha256 == judge_module.judge_prompt_sha256(JUDGE)

    collapsed = FakeJudgeClient(
        [_calibration_replies({answer: uniform(3) for answer in expected})] * 9
    )
    failed = run_calibration(collapsed, JUDGE, FIXTURES)
    assert failed.passed is False, "a judge that scores everything 3 has collapsed"


def test_bench_judge_calibration_payload_strips_the_source():
    document = load_calibration()
    answer = document["answers"][0]
    payload = judge_module._calibration_payload(answer, FIXTURES[answer["scenario"]])
    assert set(payload) == {
        "athlete_data",
        "tool_results",
        "question",
        "answer",
        "truncated",
    }
    rendered = json.dumps(payload)
    assert "record_id" not in rendered
    assert "opencode-deepseek" not in rendered
    assert "rationale" not in rendered


def test_bench_judge_prompt_is_the_canonical_text():
    prompt = JUDGE["prompt"]
    assert prompt.startswith("You are scoring one answer from a running-coach")
    assert "ACTIONABILITY (weight 0.30)" in prompt
    assert '"confidence":"high|medium|low"' in prompt


def _write_record(path, *, model_key: str = "candidate", answer: str = ANSWER) -> None:
    _write_records(path, [make_record(answer=answer, model_key=model_key)])


def _write_records(path, rows) -> None:
    from bench import records

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            row = dict(row)
            row["fixture"] = {
                "scenario": row["fixture"]["scenario"],
                "version": 1,
                "snapshot_sha256": FIXTURES[row["fixture"]["scenario"]].snapshot_sha256,
                "tool_context_sha256": FIXTURES[
                    row["fixture"]["scenario"]
                ].tool_context_sha256,
            }
            handle.write(records.serialize_record(row) + "\n")


def calibration_reply_factory():
    """A judge double that reproduces the hand scores, and 3 for anything else."""
    document = load_calibration()
    expected = {
        answer["answer"]: {
            dimension: int(answer["expected"][dimension]) for dimension in DIMENSIONS
        }
        for answer in document["answers"]
    }

    def reply(_system: str, user: str) -> str:
        payload = json.loads(user)
        answer = payload["answer"]
        scores = expected.get(answer, uniform(3))
        rationale = (
            "The answer names the knee, the limiting constraint, and a tempo plan."
            if max(scores.values()) == 5
            else "The answer mentions readiness and runs, but gives no recommendation."
            if max(scores.values()) == 1
            else "The answer is clear and usable."
        )
        return make_reply(answer, scores, rationale=rationale)

    return reply


def test_bench_score_with_judge_writes_audit_fields(tmp_path, monkeypatch):
    from bench.cli import main
    from bench.scoring import judge_client

    _write_record(tmp_path / config.RECORDS_FILENAME)
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {"plan_hash": "plan-hash", "rubric_hash": RUBRIC.sha256},
            }
        ),
        encoding="utf-8",
    )
    reply = calibration_reply_factory()

    monkeypatch.setattr(
        judge_client,
        "OpenAICompatibleJudgeClient",
        lambda **_kwargs: FakeJudgeClient([reply] * 40, model_id="judge-x"),
    )
    code = main(
        [
            "score",
            str(tmp_path),
            "--judge",
            "judge-x",
            "--judge-base-url",
            "https://example.test/v1",
            "--judge-key-env",
            "TEST_JUDGE_KEY",
            "--quiet",
        ]
    )
    assert code == 0
    entry = json.loads(
        (tmp_path / config.SCORES_FILENAME).read_text(encoding="utf-8").splitlines()[0]
    )
    assert entry["judge_status"] == "ok"
    assert entry["judge"] == 3.0
    assert entry["judge_meta"]["prompt_sha256"] == judge_module.judge_prompt_sha256(
        JUDGE
    )
    assert len(entry["judge_meta"]["reply_sha256"]) == 3
    # The budget and per-call attempts are recorded with the score, not just
    # in the process that produced it.
    assert entry["judge_meta"]["max_tokens"] == config.JUDGE_MAX_TOKENS
    assert entry["judge_meta"]["attempts"] == 3
    assert len(entry["judge_meta"]["call_log"]) == 3
    assert all(
        call["max_tokens"] == config.JUDGE_MAX_TOKENS
        for call in entry["judge_meta"]["call_log"]
    )
    meta = json.loads((tmp_path / config.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["judge"]["model"] == "judge-x"
    assert meta["judge"]["calibration"]["passed"] is True


def test_bench_score_refuses_a_judge_under_test(tmp_path, capsys):
    from bench import config
    from bench.cli import main

    _write_record(tmp_path / config.RECORDS_FILENAME, model_key="judge-x")
    code = main(
        [
            "score",
            str(tmp_path),
            "--judge",
            "judge-x",
            "--judge-base-url",
            "https://example.test/v1",
            "--quiet",
        ]
    )
    assert code == 2
    assert "model under test" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Cost control and key hygiene in the score pass
# ---------------------------------------------------------------------------


def test_bench_score_judge_repeats_judges_only_early_repeats(tmp_path, monkeypatch):
    from bench.cli import main
    from bench.scoring import aggregate
    from bench.scoring import judge_client as judge_client_module

    _write_records(
        tmp_path / config.RECORDS_FILENAME,
        [
            make_record(record_id="rec-0", repeat=0),
            make_record(record_id="rec-1", repeat=1),
        ],
    )
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {
                    "plan_hash": "plan-hash",
                    "rubric_hash": RUBRIC.sha256,
                    "judge_model": "judge-x",
                },
            }
        ),
        encoding="utf-8",
    )
    reply = calibration_reply_factory()
    monkeypatch.setattr(
        judge_client_module,
        "OpenAICompatibleJudgeClient",
        lambda **_kwargs: FakeJudgeClient([reply] * 40, model_id="judge-x"),
    )

    code = main(
        [
            "score",
            str(tmp_path),
            "--judge",
            "judge-x",
            "--judge-base-url",
            "https://example.test/v1",
            "--judge-key-env",
            "TEST_JUDGE_KEY",
            "--judge-repeats",
            "0",
            "--quiet",
        ]
    )

    assert code == 0
    entries = [
        json.loads(line)
        for line in (tmp_path / config.SCORES_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    by_repeat = {entry["repeat"]: entry for entry in entries}
    assert by_repeat[0]["judge_status"] == "ok"
    assert by_repeat[0]["judge"] == 3.0
    assert by_repeat[1]["judge_status"] == "judge_missing"
    assert by_repeat[1]["judge"] is None
    assert by_repeat[1]["judge_meta"]["skipped"] == "judge-repeats"

    summary = aggregate(entries, load_rubric(), min_answers=1, min_cells=1)
    model = summary["models"][0]
    assert model["judge_missing"] == 1
    # The judged answer is a FAIL cell, so the PASS-only §9.2 mean has no
    # answer to average; the judge value is stored but not aggregated.
    assert by_repeat[0]["gate"] == "fail"
    assert model["judge_answers"] == 0
    assert model["judge_mean"] is None


def test_bench_score_redacts_a_judge_key_in_an_exception(tmp_path, monkeypatch, capsys):
    """A provider error echoing the key must not reach disk or the terminal."""
    from bench.cli import main
    from bench.scoring import judge_client as judge_client_module

    key = "sk-judge-0123456789abcdef"
    monkeypatch.setenv("BENCH_TEST_JUDGE_KEY", key)
    _write_record(tmp_path / config.RECORDS_FILENAME)
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {
                    "plan_hash": "plan-hash",
                    "rubric_hash": RUBRIC.sha256,
                    "judge_model": "judge-x",
                },
            }
        ),
        encoding="utf-8",
    )
    reply = calibration_reply_factory()

    class LeakingJudge:
        """Valid replies for the three calibration answers, then a leaky error."""

        model_id = "judge-x"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, user, *, max_tokens=None):
            self.calls += 1
            if self.calls > 9:
                raise RuntimeError(f"HTTP 401: rejected key {key}")
            return JudgeReply(text=reply(system, user))

    monkeypatch.setattr(
        judge_client_module,
        "OpenAICompatibleJudgeClient",
        lambda **_kwargs: LeakingJudge(),
    )

    code = main(
        [
            "score",
            str(tmp_path),
            "--judge",
            "judge-x",
            "--judge-base-url",
            "https://example.test/v1",
            "--judge-key-env",
            "BENCH_TEST_JUDGE_KEY",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    for path in (
        tmp_path / config.SCORES_FILENAME,
        tmp_path / config.META_FILENAME,
    ):
        assert key not in path.read_text(encoding="utf-8")
    assert key not in captured.out
    assert key not in captured.err

    entry = json.loads(
        (tmp_path / config.SCORES_FILENAME).read_text(encoding="utf-8").splitlines()[0]
    )
    assert entry["judge_status"] == "judge-invalid"
    assert config.REDACTION_PLACEHOLDER in entry["judge_meta"]["detail"]


def test_bench_score_redacts_a_registry_resolved_judge_key(
    tmp_path, monkeypatch, capsys
):
    """Gate repro: `--judge` resolves `apiKeyEnv` from models.json."""
    from bench.cli import main
    from bench.scoring import judge_client as judge_client_module

    key = "sk-albert-registry-0123456789abcdef"
    monkeypatch.setenv("ALBERT_API_KEY", key)
    _write_record(tmp_path / config.RECORDS_FILENAME)
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {
                    "plan_hash": "plan-hash",
                    "rubric_hash": RUBRIC.sha256,
                    "judge_model": "albert-qwen",
                },
            }
        ),
        encoding="utf-8",
    )
    reply = calibration_reply_factory()

    class LeakingJudge:
        model_id = "albert-qwen"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system, user, *, max_tokens=None):
            self.calls += 1
            if self.calls > 9:
                raise RuntimeError(f"HTTP 500: rejected key {key}")
            return JudgeReply(text=reply(system, user))

    monkeypatch.setattr(
        judge_client_module,
        "OpenAICompatibleJudgeClient",
        lambda **_kwargs: LeakingJudge(),
    )

    # No --judge-base-url: the registry entry supplies URL, model and key env.
    code = main(["score", str(tmp_path), "--judge", "albert-qwen"])

    assert code == 0
    captured = capsys.readouterr()
    for path in (
        tmp_path / config.SCORES_FILENAME,
        tmp_path / config.META_FILENAME,
    ):
        assert key not in path.read_text(encoding="utf-8")
    assert key not in captured.out
    assert key not in captured.err
    entry = json.loads(
        (tmp_path / config.SCORES_FILENAME).read_text(encoding="utf-8").splitlines()[0]
    )
    assert config.REDACTION_PLACEHOLDER in entry["judge_meta"]["detail"]


def test_bench_score_redacts_a_judge_key_when_calibration_fails(
    tmp_path, monkeypatch, capsys
):
    from bench.cli import main
    from bench.scoring import judge_client as judge_client_module

    key = "sk-albert-calibration-0123456789abcdef"
    monkeypatch.setenv("ALBERT_API_KEY", key)
    _write_record(tmp_path / config.RECORDS_FILENAME)
    (tmp_path / config.META_FILENAME).write_text(
        json.dumps(
            {
                "sweep": "unit",
                "plan": {
                    "plan_hash": "plan-hash",
                    "rubric_hash": RUBRIC.sha256,
                    "judge_model": "albert-qwen",
                },
            }
        ),
        encoding="utf-8",
    )

    class FailingJudge:
        model_id = "albert-qwen"

        def complete(self, system, user, *, max_tokens=None):
            raise RuntimeError(f"HTTP 401: bad key {key}")

    monkeypatch.setattr(
        judge_client_module,
        "OpenAICompatibleJudgeClient",
        lambda **_kwargs: FailingJudge(),
    )

    code = main(["score", str(tmp_path), "--judge", "albert-qwen"])

    assert code == 2
    captured = capsys.readouterr()
    assert key not in captured.out
    assert key not in captured.err
    assert config.REDACTION_PLACEHOLDER in captured.err
    assert not (tmp_path / config.SCORES_FILENAME).exists()


def test_bench_judge_reasoning_only_retries_with_double_budget():
    """The 700-token thinking failure is retried with twice the output budget."""
    client = FakeJudgeClient(
        [
            JudgeReply(text="", finish_reason="length", reasoning_chars=900),
            make_reply(ANSWER, uniform(3)),
        ]
        + [make_reply(ANSWER, uniform(3))] * 2
    )

    cell = judge_answer(make_record(), FIXTURES["red_flags"], PROMPT, client, JUDGE)

    assert cell.status == "ok"
    assert cell.calls == 4  # 2 turns for the first reply, then 1 + 1
    assert [call.outcome for call in cell.call_log] == [
        "reasoning_only",
        "parsed",
        "parsed",
        "parsed",
    ]
    assert client.budgets == [1500, 3000, 1500, 1500]
    assert cell.call_log[1].max_tokens == 3000


def test_bench_judge_contract_violation_retries_once_then_is_invalid():
    """A 1/5 rationale under the word floor gets one retry, then no score."""
    payload = json.loads(make_reply(ANSWER, uniform(1)))
    payload["rationale"]["actionability"] = "too vague"
    bad = json.dumps(payload)
    client = FakeJudgeClient([bad, bad])

    cell = judge_answer(make_record(), FIXTURES["red_flags"], PROMPT, client, JUDGE)

    assert cell.status == "judge-invalid"
    assert cell.dimensions is None
    assert cell.calls == 2
    assert "word floor" in cell.detail
    assert "Output only the JSON object" in client.calls[1][1]
    assert cell.call_log[0].outcome == "invalid"


def test_bench_judge_contract_violation_can_recover_on_the_retry():
    payload = json.loads(make_reply(ANSWER, uniform(1)))
    payload["rationale"]["actionability"] = "too vague"
    bad = json.dumps(payload)
    client = FakeJudgeClient(
        [bad, make_reply(ANSWER, uniform(3))] + [make_reply(ANSWER, uniform(3))] * 2
    )

    cell = judge_answer(make_record(), FIXTURES["red_flags"], PROMPT, client, JUDGE)

    assert cell.status == "ok"
    assert cell.calls == 4  # the rejected reply plus its retry, then 1 + 1
    assert cell.dimensions["actionability"] == 3.0


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_judge_transport_paces_and_retries_429(monkeypatch):
    """Albert's 10 req/min rule: every turn is paced, a 429 backs off."""
    from email.message import Message
    from urllib.error import HTTPError

    from app import coach_llm
    from bench.scoring.judge_client import OpenAICompatibleJudgeClient

    clock = _FakeClock()
    sends: list[float] = []

    def fake_send(model, messages, tools=None):
        sends.append(clock.now)
        if len(sends) == 1:
            cause = HTTPError("https://example.test/v1", 429, "429", Message(), None)
            error = coach_llm.LLMError("judge returned HTTP 429: slow down")
            error.__cause__ = cause
            raise error
        return coach_llm.SendResult({"content": '{"ok":true}'}, None, "stop")

    monkeypatch.setattr(coach_llm, "_send", fake_send)
    client = OpenAICompatibleJudgeClient(
        model_id="judge-x",
        base_url="https://example.test/v1",
        min_interval_s=6.5,
        clock=clock,
        sleep=clock.sleep,
        rng=lambda _low, _high: 5.0,
        timeout_s=120,
    )

    first = client.complete("system", "user")
    second = client.complete("system", "user")

    assert first.text == '{"ok":true}'
    assert second.text == '{"ok":true}'
    assert sends[1] - sends[0] >= 6.5, "the retry is paced too"
    assert sends[2] - sends[1] >= 6.5, "the next call waits for the pacer"
    assert clock.sleeps[0] == 5.0, "429 backoff"
    assert clock.sleeps[1] == 1.5, "pacer tops the retry up to 6.5 s"
