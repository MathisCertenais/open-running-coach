"""ChatTrace: the production seam the benchmark reads."""

from __future__ import annotations

import json

from app import coach_llm

MODEL = {
    "id": "test",
    "name": "Test model",
    "model": "test-model",
    "base_url": "http://127.0.0.1:1/v1",
    "chat_path": "/chat/completions",
    "temperature": 0.4,
    "max_tokens": 500,
    "tools": True,
}


def test_snapshot_payload_truncates_once(monkeypatch):
    monkeypatch.setattr(coach_llm, "LLM_CONTEXT_MAX_CHARS", 10)
    snapshot = {"athlete": "x" * 50}

    payload, truncated = coach_llm.snapshot_payload(snapshot)
    messages = coach_llm.build_messages(snapshot, [], "q")

    assert truncated is True
    assert payload.endswith("... (truncated)")
    assert messages[0]["content"].endswith(payload)
    assert messages[0]["content"].count("... (truncated)") == 1


def test_run_chat_reports_tool_calls_and_sums_usage(monkeypatch):
    responses = [
        coach_llm.SendResult(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "search_activities",
                            "arguments": json.dumps({"limit": 3}),
                        },
                    }
                ],
            },
            {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            "tool_calls",
        ),
        coach_llm.SendResult(
            {"content": "You ran three times."},
            {"prompt_tokens": 150, "completion_tokens": 20, "total_tokens": 170},
            "stop",
        ),
    ]

    def fake_send(model, messages, tools=None):
        return responses.pop(0)

    monkeypatch.setattr(coach_llm, "_send", fake_send)

    trace = coach_llm.run_chat(
        {"load": {}},
        [],
        "question",
        MODEL,
        {"activities": [], "rpe": {}, "feedback": {}, "notes": {}, "sessions": []},
    )

    assert trace.text == "You ran three times."
    assert trace.rounds == 2
    assert trace.finish_reason == "stop"
    assert trace.tools_offered == len(coach_llm.coach_tools.TOOL_SCHEMAS)
    assert trace.tools_dropped is False
    assert trace.usage == {
        "prompt_tokens": 250,
        "completion_tokens": 30,
        "total_tokens": 280,
    }
    assert trace.context_truncated is False
    assert trace.tool_calls[0].round == 1
    assert trace.tool_calls[0].name == "search_activities"
    assert trace.tool_calls[0].arguments == {"limit": 3}
    assert trace.tool_calls[0].result["matched"] == 0


def test_run_chat_marks_tools_dropped(monkeypatch):
    calls = []

    def fake_send(model, messages, tools=None):
        calls.append(tools)
        if tools:
            raise coach_llm.LLMError("Test model returned HTTP 400: no tools")
        return coach_llm.SendResult({"content": "Answer."}, None, "stop")

    monkeypatch.setattr(coach_llm, "_send", fake_send)

    trace = coach_llm.run_chat({}, [], "q", MODEL, {"activities": []})

    assert trace.text == "Answer."
    assert trace.tools_dropped is True
    assert trace.rounds == 1
    assert len(calls) == 2


def test_run_chat_accepts_a_send_result(monkeypatch):
    """A stubbed transport returns the same ``SendResult`` production returns."""
    monkeypatch.setattr(
        coach_llm,
        "_send",
        lambda model, messages, tools=None: coach_llm.SendResult(
            {"content": "Short answer."}, None, None
        ),
    )

    trace = coach_llm.run_chat({}, [], "q", MODEL)

    assert trace.text == "Short answer."
    assert trace.usage is None
    assert trace.finish_reason is None


def test_find_model_sees_unconfigured_entries(monkeypatch):
    entry = {
        "id": "no-key",
        "name": "No key",
        "roles": ["chat"],
        "model": "m",
        "base_url": "https://example.invalid/v1",
        "api_key": "",
    }
    monkeypatch.setattr(coach_llm, "MODELS", [entry])

    assert coach_llm.find_model("no-key") is entry
    assert coach_llm.find_model("unknown") is None
    assert coach_llm._resolve_model("no-key") is None
