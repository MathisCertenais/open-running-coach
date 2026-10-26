"""The production send path: roster headers, $uuid expansion, Authorization."""

from __future__ import annotations

import json
import uuid

from app import coach_llm


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ).encode("utf-8")


MODEL = {
    "id": "test",
    "name": "Test model",
    "model": "test-model",
    "base_url": "https://example.test/v1",
    "chat_path": "/chat/completions",
    "temperature": 0.4,
    "max_tokens": 900,
    "api_key": "secret-key",
    "timeout_s": 5.0,
}


def _send_and_capture(monkeypatch, headers):
    requests = []

    def fake_urlopen(request, timeout=None):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(coach_llm.urllib.request, "urlopen", fake_urlopen)
    model = {**MODEL, "headers": headers}
    coach_llm._send(model, [{"role": "user", "content": "hi"}])
    coach_llm._send(model, [{"role": "user", "content": "hi"}])
    return [{k.lower(): v for k, v in request.headers.items()} for request in requests]


def test_roster_headers_are_sent_with_a_fresh_uuid(monkeypatch):
    sent = _send_and_capture(
        monkeypatch, {"x-opencode-session": "$uuid", "x-literal": "fixed"}
    )

    first, second = sent
    uuid.UUID(first["x-opencode-session"])
    uuid.UUID(second["x-opencode-session"])
    assert first["x-opencode-session"] != second["x-opencode-session"]
    assert first["x-literal"] == "fixed"
    assert first["authorization"] == "Bearer secret-key"


def test_authorization_cannot_be_overridden(monkeypatch):
    sent = _send_and_capture(
        monkeypatch,
        {"Authorization": "Bearer evil", "authorization": "Bearer evil-too"},
    )

    assert sent[0]["authorization"] == "Bearer secret-key"


def test_registry_entry_keeps_its_headers():
    """A model added to models.json must not lose its headers on normalisation."""
    model = coach_llm._normalize(
        {
            "name": "Gateway",
            "model": "some-model",
            "apiBase": "https://gateway.example/v1",
            "headers": {"x-opencode-session": "$uuid"},
        }
    )

    assert model["headers"] == {"x-opencode-session": "$uuid"}
