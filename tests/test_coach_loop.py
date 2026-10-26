"""Tests for the tool-calling loop in the coach client."""

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

CONTEXT = {"activities": [], "rpe": {}, "feedback": {}, "notes": {}, "sessions": []}


def run_chat(monkeypatch, responses, context=CONTEXT):
    calls = []

    def fake_send(model, messages, tools=None):
        calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not responses:
            raise AssertionError("the model was called more times than expected")
        return coach_llm.SendResult(responses.pop(0), None, None)

    monkeypatch.setattr(coach_llm, "_send", fake_send)
    monkeypatch.setattr(coach_llm, "_model_or_error", lambda model_id: MODEL)
    reply = coach_llm.chat({}, [], "question", "test", tool_context=context)
    return reply, calls


def test_a_plain_answer_needs_one_call(monkeypatch):
    reply, calls = run_chat(monkeypatch, [{"content": "Just run easy."}])

    assert reply == "Just run easy."
    assert len(calls) == 1
    assert calls[0]["tools"] is not None


def test_the_model_can_call_a_tool_then_answer(monkeypatch):
    reply, calls = run_chat(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search_activities",
                            "arguments": json.dumps({"limit": 3}),
                        },
                    }
                ],
            },
            {"content": "You ran three times."},
        ],
    )

    assert reply == "You ran three times."
    assert len(calls) == 2
    tool_messages = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_messages and tool_messages[0]["tool_call_id"] == "call-1"
    assert "matched" in json.loads(tool_messages[0]["content"])


def test_an_unknown_tool_is_returned_to_the_model(monkeypatch):
    reply, calls = run_chat(
        monkeypatch,
        [
            {
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "drop_database", "arguments": "{}"},
                    }
                ]
            },
            {"content": "I could not do that."},
        ],
    )

    assert reply == "I could not do that."
    tool_messages = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
    assert "error" in json.loads(tool_messages[0]["content"])


def test_malformed_tool_arguments_are_reported(monkeypatch):
    reply, calls = run_chat(
        monkeypatch,
        [
            {
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "search_activities",
                            "arguments": "{not json",
                        },
                    }
                ]
            },
            {"content": "Sorry."},
        ],
    )

    assert reply == "Sorry."
    tool_messages = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
    assert "error" in json.loads(tool_messages[0]["content"])


def test_the_tool_budget_is_enforced(monkeypatch):
    loop_call = {
        "tool_calls": [
            {"id": "c", "function": {"name": "search_activities", "arguments": "{}"}}
        ]
    }
    # The loop may spend its budget, then the final call must be tool-free.
    responses = [loop_call] * (coach_llm.LLM_MAX_TOOL_ROUNDS + 1) + [
        {"content": "Final answer."}
    ]

    reply, calls = run_chat(monkeypatch, responses)

    assert reply == "Final answer."
    assert len(calls) == coach_llm.LLM_MAX_TOOL_ROUNDS + 2
    assert calls[-1]["tools"] is None


def test_a_provider_that_rejects_tools_is_retried_without_them(monkeypatch):
    calls = []

    def fake_send(model, messages, tools=None):
        calls.append(tools)
        if tools:
            raise coach_llm.LLMError("Test model returned HTTP 400: tools unsupported")
        return coach_llm.SendResult({"content": "Answer without tools."}, None, None)

    monkeypatch.setattr(coach_llm, "_send", fake_send)
    monkeypatch.setattr(coach_llm, "_model_or_error", lambda model_id: MODEL)

    reply = coach_llm.chat({}, [], "question", "test", tool_context=CONTEXT)

    assert reply == "Answer without tools."
    assert len(calls) == 2
    assert calls[1] is None


def test_without_a_tool_context_no_tools_are_sent(monkeypatch):
    reply, calls = run_chat(monkeypatch, [{"content": "Hi"}], context=None)

    assert reply == "Hi"
    assert calls[0]["tools"] is None


def test_a_model_can_be_marked_as_not_supporting_tools(monkeypatch):
    monkeypatch.setattr(
        coach_llm, "_model_or_error", lambda model_id: {**MODEL, "tools": False}
    )
    calls = []

    def fake_send(model, messages, tools=None):
        calls.append(tools)
        return coach_llm.SendResult({"content": "No tools here."}, None, None)

    monkeypatch.setattr(coach_llm, "_send", fake_send)

    assert coach_llm.chat({}, [], "q", "test", tool_context=CONTEXT) == "No tools here."
    assert calls[0] is None


def test_a_model_can_cap_the_number_of_tool_schemas(monkeypatch):
    monkeypatch.setattr(
        coach_llm, "_model_or_error", lambda model_id: {**MODEL, "tools": 3}
    )
    calls = []

    def fake_send(model, messages, tools=None):
        calls.append(tools)
        return coach_llm.SendResult({"content": "Done."}, None, None)

    monkeypatch.setattr(coach_llm, "_send", fake_send)

    coach_llm.chat({}, [], "q", "test", tool_context=CONTEXT)

    assert len(calls[0]) == 3
    names = [schema["function"]["name"] for schema in calls[0]]
    assert names == ["search_activities", "get_activity", "best_efforts"]


def test_the_full_schema_set_is_sent_by_default(monkeypatch):
    _, calls = run_chat(monkeypatch, [{"content": "Hi"}])

    assert len(calls[0]["tools"]) == len(coach_llm.coach_tools.TOOL_SCHEMAS)


def test_chat_is_run_chat_text(monkeypatch):
    """The production wrapper must not change what callers receive."""
    captured = {}

    def fake_run_chat(snapshot, history, user_message, model, tool_context=None):
        captured.update(
            snapshot=snapshot,
            history=history,
            user_message=user_message,
            model=model,
            tool_context=tool_context,
        )
        return coach_llm.ChatTrace(
            text="The trace text.",
            tool_calls=(),
            usage=None,
            rounds=1,
            tools_offered=0,
            tools_dropped=False,
            finish_reason="stop",
            context_chars=2,
            context_truncated=False,
        )

    monkeypatch.setattr(coach_llm, "run_chat", fake_run_chat)
    monkeypatch.setattr(coach_llm, "_model_or_error", lambda model_id: MODEL)

    reply = coach_llm.chat({"a": 1}, [], "question", "test", tool_context=CONTEXT)

    assert reply == "The trace text."
    assert captured["snapshot"] == {"a": 1}
    assert captured["user_message"] == "question"
    assert captured["tool_context"] is CONTEXT
