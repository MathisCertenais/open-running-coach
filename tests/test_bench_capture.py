"""Capture loop: append-only storage, resume and per-record isolation."""

from __future__ import annotations

import json

from bench import config
from bench.providers.base import (
    Availability,
    AvailabilityStatus,
    ErrorKind,
    Status,
)
from bench.providers.fake import FakeProvider
from bench.runner import capture
from tests.bench_helpers import (
    make_completion,
    make_fixture,
    make_plan,
    make_prompt,
    make_spec,
)


def _fixtures(fixture):
    return {fixture.scenario: fixture}


def _lines(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_bench_capture_one_line_per_record(tmp_path):
    fixture = make_fixture()
    prompts = [make_prompt("this_week"), make_prompt("load_change")]
    plan = make_plan(fixtures=[fixture], prompts=prompts)
    provider = FakeProvider()

    summary = capture(
        plan,
        {"fake": provider},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
    )

    lines = _lines(tmp_path / config.RECORDS_FILENAME)
    assert len(lines) == 2
    assert summary.attempted == 2
    assert summary.ok == 2
    for line in lines:
        record = json.loads(line)
        assert record["record_id"] in {item.id for item in plan.items}
        assert record["status"] == "ok"


def test_bench_capture_resumes_without_recalling(tmp_path):
    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    first = FakeProvider()
    capture(plan, {"fake": first}, tmp_path, _fixtures(fixture), sweep="test")

    second = FakeProvider()
    summary = capture(
        plan, {"fake": second}, tmp_path, _fixtures(fixture), sweep="test"
    )

    assert second.requests == []
    assert summary.skipped_existing == 1
    assert summary.attempted == 0
    assert len(_lines(tmp_path / config.RECORDS_FILENAME)) == 1


def test_bench_capture_persists_raw_for_a_failed_call(tmp_path):
    """A failed CLI call must be diagnosable without having passed --keep-raw."""
    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    failure = make_completion(
        text="",
        status=Status.EMPTY,
        error_kind=ErrorKind.EMPTY,
        error_message="no visible text",
        diagnostics={
            "raw_events": ['{"type":"step_finish","part":{"reason":"length"}}']
        },
    )
    provider = FakeProvider(default=failure)

    capture(
        plan,
        {"fake": provider},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
        keep_raw=False,
    )

    raw = tmp_path / config.RAW_DIRNAME / f"{plan.items[0].id}.jsonl"
    assert raw.exists(), "a failed call always keeps its raw event stream"
    assert "step_finish" in raw.read_text(encoding="utf-8")


def test_bench_capture_ignores_truncated_tail(tmp_path):
    fixture = make_fixture()
    prompts = [make_prompt("this_week"), make_prompt("load_change")]
    plan = make_plan(fixtures=[fixture], prompts=prompts)
    capture(
        plan,
        {"fake": FakeProvider()},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
    )

    path = tmp_path / config.RECORDS_FILENAME
    lines = _lines(path)
    path.write_text(lines[0] + "\n" + '{"record_id": "cut', encoding="utf-8")

    second = FakeProvider()
    summary = capture(
        plan, {"fake": second}, tmp_path, _fixtures(fixture), sweep="test"
    )

    assert [request.user_message for request in second.requests] == [prompts[1].text]
    assert summary.attempted == 1
    assert summary.ok == 1


def test_bench_capture_survives_a_raising_provider(tmp_path):
    fixture = make_fixture()
    models = [make_spec("good", adapter="fake"), make_spec("bad", adapter="fake")]
    plan = make_plan(models=models, fixtures=[fixture])
    provider = FakeProvider(raise_for={"bad"})

    summary = capture(
        plan, {"fake": provider}, tmp_path, _fixtures(fixture), sweep="test"
    )

    assert summary.attempted == 2
    assert summary.failed == 1
    records = [json.loads(line) for line in _lines(tmp_path / config.RECORDS_FILENAME)]
    assert len(records) == 2
    failed = next(row for row in records if row["status"] == "error")
    assert failed["error"]["kind"] == "server"
    assert "Traceback" not in json.dumps(failed)


def test_bench_capture_marks_auth_error(tmp_path):
    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    completion = make_completion(
        text="",
        status=Status.ERROR,
        error_kind=ErrorKind.AUTH,
        error_message="HTTP 401: bad key",
    )
    provider = FakeProvider(responses={"model-a": completion})

    capture(plan, {"fake": provider}, tmp_path, _fixtures(fixture), sweep="test")

    record = json.loads(_lines(tmp_path / config.RECORDS_FILENAME)[0])
    assert record["status"] == "error"
    assert record["error"]["kind"] == "auth"
    assert record["answer"] == ""


def test_bench_capture_marks_empty_and_thinking_only(tmp_path):
    fixture = make_fixture()
    models = [make_spec("empty"), make_spec("thinking")]
    plan = make_plan(models=models, fixtures=[fixture])
    provider = FakeProvider(
        responses={
            "empty": make_completion(
                text="",
                status=Status.EMPTY,
                error_kind=ErrorKind.EMPTY,
                error_message="empty response",
            ),
            "thinking": make_completion(
                text="",
                status=Status.ERROR,
                error_kind=ErrorKind.THINKING_ONLY,
                error_message="only hidden reasoning",
            ),
        }
    )

    capture(plan, {"fake": provider}, tmp_path, _fixtures(fixture), sweep="test")

    records = [json.loads(line) for line in _lines(tmp_path / config.RECORDS_FILENAME)]
    kinds = {row["model"]["key"]: row["error"]["kind"] for row in records}
    assert kinds == {"empty": "empty", "thinking": "thinking_only"}


class _EchoProvider:
    """A provider that leaks a secret in both a success and a failure."""

    adapter = "fake"

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def availability(self, spec):
        return Availability(AvailabilityStatus.OK)

    def complete(self, request):
        if request.model.key == "leaky":
            raise RuntimeError(f"request failed with key {self.secret}")
        return make_completion(text=f"here is the key {self.secret}")


def test_bench_redaction_removes_keys(tmp_path, capsys):
    fixture = make_fixture()
    models = [make_spec("answer"), make_spec("leaky")]
    plan = make_plan(models=models, fixtures=[fixture])
    secret = "sk-live-0123456789abcdef"

    capture(
        plan,
        {"fake": _EchoProvider(secret)},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
        secrets=[secret],
    )

    captured = capsys.readouterr()
    on_disk = (tmp_path / config.RECORDS_FILENAME).read_text(encoding="utf-8")
    assert secret not in on_disk
    assert secret not in captured.out
    assert secret not in captured.err
    assert config.REDACTION_PLACEHOLDER in on_disk


def test_bench_capture_skips_unavailable_models(tmp_path):
    fixture = make_fixture()
    models = [make_spec("ok", adapter="fake"), make_spec("gone", adapter="gone")]
    plan = make_plan(models=models, fixtures=[fixture])
    available = FakeProvider()
    unavailable = FakeProvider(
        availability=Availability(
            AvailabilityStatus.MISSING_KEY, "MISSING_API_KEY is not set"
        )
    )

    summary = capture(
        plan,
        {"fake": available, "gone": unavailable},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
    )

    assert summary.skipped_unavailable == 1
    assert summary.unavailable == {"gone": "missing_key"}
    assert unavailable.requests == []
    records = [json.loads(line) for line in _lines(tmp_path / config.RECORDS_FILENAME)]
    assert [row["model"]["key"] for row in records] == ["ok"]


def test_bench_capture_force_recalls_finished_records(tmp_path):
    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    first = FakeProvider()
    capture(plan, {"fake": first}, tmp_path, _fixtures(fixture), sweep="test")

    second = FakeProvider()
    summary = capture(
        plan,
        {"fake": second},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
        force=True,
    )

    assert summary.attempted == 1
    assert len(second.requests) == 1
    assert len(_lines(tmp_path / config.RECORDS_FILENAME)) == 2


def test_bench_capture_keep_raw_writes_full_tool_results(tmp_path):
    from dataclasses import replace

    from bench.providers.base import ToolCall

    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    completion = replace(
        make_completion(),
        tool_calls=(
            ToolCall(
                round=1,
                name="search_activities",
                arguments={"limit": 3},
                result={"matched": 12, "activities": ["run-1"]},
            ),
        ),
    )
    capture(
        plan,
        {"fake": FakeProvider(default=completion)},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
        keep_raw=True,
    )

    raw = tmp_path / config.RAW_DIRNAME / f"{plan.items[0].id}.jsonl"
    payload = json.loads(raw.read_text(encoding="utf-8").splitlines()[0])
    assert payload["result"]["matched"] == 12


def test_bench_capture_summary_counts_retries_and_wait(tmp_path):
    """A call that survived a rate limit must be visible in the summary."""
    fixture = make_fixture()
    plan = make_plan(fixtures=[fixture])
    completion = make_completion(
        diagnostics={
            "attempts": 2,
            "retried": True,
            "retry_reasons": ["429"],
            "retry_wait_ms": 4000,
            "rate_limit_wait_ms": 2500,
        }
    )

    summary = capture(
        plan,
        {"fake": FakeProvider(default=completion)},
        tmp_path,
        _fixtures(fixture),
        sweep="test",
    )

    assert summary.retries_by_model == {"model-a": 1}
    assert summary.retry_reasons == {"429": 1}
    assert summary.rate_limit_wait_s == 2.5
    assert summary.as_dict()["retries_by_model"] == {"model-a": 1}
    record = json.loads(_lines(tmp_path / config.RECORDS_FILENAME)[0])
    assert record["attempts"] == 2
    assert record["retried"] is True
    assert record["retry_reasons"] == ["429"]
