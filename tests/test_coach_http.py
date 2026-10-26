"""Tests for the HTTP call the coach makes to a model endpoint."""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from app import coach_llm

MODEL = {
    "id": "test",
    "name": "Test model",
    "model": "test-model",
    "base_url": "https://gateway.example.com/v1",
    "chat_path": "/chat/completions",
    "temperature": 0.4,
    "max_tokens": 500,
    "tools": True,
    "api_key": "sk-secret",
}


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture_request(monkeypatch, payload=None):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(payload or {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_a_user_agent_is_sent_because_cloudflare_blocks_the_urllib_default(monkeypatch):
    seen = capture_request(monkeypatch)

    coach_llm._send(MODEL, [{"role": "user", "content": "hi"}])

    assert seen["headers"]["user-agent"] == coach_llm.LLM_USER_AGENT
    assert "python-urllib" not in seen["headers"]["user-agent"].lower()


def test_the_key_is_sent_as_a_bearer_token_and_never_in_the_body(monkeypatch):
    seen = capture_request(monkeypatch)

    coach_llm._send(MODEL, [{"role": "user", "content": "hi"}])

    assert seen["headers"]["authorization"] == "Bearer sk-secret"
    assert "sk-secret" not in json.dumps(seen["body"])


def test_the_chat_path_is_appended_to_the_base_url(monkeypatch):
    seen = capture_request(monkeypatch)

    coach_llm._send(MODEL, [{"role": "user", "content": "hi"}])

    assert seen["url"] == "https://gateway.example.com/v1/chat/completions"


def test_an_http_error_carries_the_provider_body(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(coach_llm.LLMError) as exc:
        coach_llm._send(MODEL, [{"role": "user", "content": "hi"}])

    assert "403" in str(exc.value)
    assert "error code: 1010" in str(exc.value)


def test_extra_headers_are_sent(monkeypatch):
    seen = capture_request(monkeypatch)
    model = dict(MODEL, headers={"x-opencode-session": "abc"})

    coach_llm._send(model, [{"role": "user", "content": "hi"}])

    assert seen["headers"]["x-opencode-session"] == "abc"


def test_the_session_placeholder_is_resolved(monkeypatch):
    seen = capture_request(monkeypatch)
    model = dict(MODEL, headers={"x-opencode-session": "{session}"})

    coach_llm._send(model, [{"role": "user", "content": "hi"}])

    sent = seen["headers"]["x-opencode-session"]
    assert sent and "{session}" not in sent
    assert sent == coach_llm.SESSION_ID


def test_the_session_id_is_stable_across_requests(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append(dict(request.header_items()))
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    model = dict(MODEL, headers={"x-opencode-session": "{session}"})

    coach_llm._send(model, [{"role": "user", "content": "one"}])
    coach_llm._send(model, [{"role": "user", "content": "two"}])

    sessions = [{k.lower(): v for k, v in h.items()}["x-opencode-session"] for h in seen]
    assert sessions[0] == sessions[1]


def test_a_transport_header_cannot_be_overridden(monkeypatch):
    seen = capture_request(monkeypatch)
    model = dict(MODEL, headers={"content-type": "text/plain", "host": "evil"})

    coach_llm._send(model, [{"role": "user", "content": "hi"}])

    assert seen["headers"]["content-type"] == "application/json"
    assert "evil" not in json.dumps(seen["headers"])
