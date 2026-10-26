"""Record schema, serialisation and redaction."""

from __future__ import annotations

import json
from dataclasses import replace

from bench import config, records
from bench.providers.base import ErrorKind, Status, ToolCall, Usage
from tests.bench_helpers import NOW, make_completion, make_plan


def test_bench_record_roundtrip():
    plan = make_plan()
    completion = make_completion(text="Line one.\nLine two.")
    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")

    assert record["schema_version"] == config.BENCH_SCHEMA_VERSION
    assert record["record_id"] == plan.items[0].id
    assert record["plan_hash"] == plan.plan_hash
    assert record["answer"] == "Line one.\nLine two."
    assert record["status"] == "ok"
    assert record["model"]["key"] == plan.items[0].model.key
    assert record["fixture"]["scenario"] == plan.items[0].fixture.scenario
    assert record["prompt"]["id"] == plan.items[0].prompt.id

    parsed = records.parse_record(records.serialize_record(record))
    assert parsed == record


def test_bench_record_failed_status_has_no_answer():
    plan = make_plan()
    completion = make_completion(
        text="this should not be stored",
        status=Status.ERROR,
        error_kind=ErrorKind.AUTH,
        error_message="HTTP 401 from provider",
    )
    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")

    assert record["status"] == "error"
    assert record["answer"] == ""
    assert record["error"] == {
        "kind": "auth",
        "message": "HTTP 401 from provider",
    }
    assert "Traceback" not in json.dumps(record)


def test_bench_record_usage_is_null_when_unreported():
    plan = make_plan()
    completion = make_completion(usage=Usage(source="unknown"))
    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")

    assert record["usage"] is None
    assert record["cost_usd"] is None


def test_bench_record_preview_is_capped():
    plan = make_plan()
    completion = replace(
        make_completion(),
        tool_calls=(
            ToolCall(
                round=1,
                name="search_activities",
                arguments={"limit": 5},
                result={"payload": "x" * (config.BENCH_PREVIEW_CHARS * 2)},
            ),
        ),
    )
    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")
    call = record["tool_calls"][0]
    assert len(call["result_preview"]) == config.BENCH_PREVIEW_CHARS
    assert len(call["result_sha256"]) == 64
    assert call["ok"] is True
    assert record["tool_rounds"] == 1


def test_bench_redaction_removes_keys():
    plan = make_plan()
    secret = "sk-test-very-secret-key"
    answer_record = records.build_record(
        plan,
        plan.items[0],
        make_completion(text=f"The key is {secret}"),
        NOW,
        sweep="test",
        secrets=[secret],
    )
    error_record = records.build_record(
        plan,
        plan.items[0],
        make_completion(
            text="",
            status=Status.ERROR,
            error_kind=ErrorKind.AUTH,
            error_message=f"auth failed with {secret}",
        ),
        NOW,
        sweep="test",
        secrets=[secret],
    )

    serialized = records.serialize_record(answer_record)
    assert secret not in serialized
    assert config.REDACTION_PLACEHOLDER in answer_record["answer"]
    assert config.REDACTION_PLACEHOLDER in error_record["error"]["message"]


def test_bench_secret_values_reads_every_named_value(monkeypatch):
    monkeypatch.setenv("LONG_KEY", "0123456789abcdef")
    monkeypatch.setenv("SHORT_KEY", "abc")

    assert records.secret_values(["LONG_KEY", "SHORT_KEY", "MISSING"]) == (
        "0123456789abcdef",
        "abc",
    )


def test_bench_read_records_ignores_truncated_tail(tmp_path, caplog):
    path = tmp_path / "records.jsonl"
    first = records.serialize_record({"record_id": "a", "status": "ok"})
    second = records.serialize_record({"record_id": "b", "status": "ok"})
    path.write_text(
        first + "\n" + second + "\n" + '{"record_id": "c"', encoding="utf-8"
    )

    with caplog.at_level("WARNING"):
        parsed = list(records.read_records(path))

    assert [row["record_id"] for row in parsed] == ["a", "b"]
    assert "truncated last record" in caplog.text


def test_bench_read_records_skips_a_malformed_middle_line(tmp_path, caplog):
    path = tmp_path / "records.jsonl"
    valid = records.serialize_record({"record_id": "a", "status": "ok"})
    path.write_text(valid + "\n{broken\n" + valid + "\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        parsed = list(records.read_records(path))

    assert len(parsed) == 2
    assert "malformed record" in caplog.text


def test_bench_record_notes_are_serialised():
    plan = make_plan()
    completion = make_completion(notes=("athlete_data_in_user_turn",))
    record = records.build_record(plan, plan.items[0], completion, NOW, sweep="test")
    assert record["notes"] == ["athlete_data_in_user_turn"]
