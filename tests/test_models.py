"""Tests for adding a model from the UI (app/coach_llm.py).

The registry files are redirected to a temporary directory: nothing here may
touch the repository's models.json, models.local.json or .env.
"""

from __future__ import annotations

import json

import pytest

from app import coach_llm


@pytest.fixture()
def registry(tmp_path):
    models = tmp_path / "models.json"
    models.write_text(
        json.dumps(
            {
                "default": "shipped",
                "models": [
                    {
                        "id": "shipped",
                        "name": "Shipped",
                        "model": "shipped-model",
                        "apiBase": "https://api.example.com/v1",
                        "apiKeyEnv": "SHIPPED_KEY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # ``reload_models()`` copies the two paths into MODELS, so the teardown
    # must undo the path patches *before* reloading. Reloading while the
    # temporary paths are still installed leaves every later test reading a
    # deleted registry, which made the suite order-dependent.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(coach_llm, "MODELS_FILE", models)
        patch.setattr(coach_llm, "LOCAL_MODELS_FILE", tmp_path / "models.local.json")
        patch.setattr(coach_llm, "ENV_FILE", tmp_path / ".env")
        patch.setenv("SHIPPED_KEY", "shipped-secret")
        coach_llm.reload_models()
        yield tmp_path
    coach_llm.reload_models()


def model_ids():
    return [m["id"] for m in coach_llm.list_models()]


def test_adding_a_model_registers_it_without_exposing_the_key(registry):
    added = coach_llm.add_model(
        {
            "name": "My Gateway",
            "model": "gpt-4o-mini",
            "apiBase": "https://api.example.com/v1",
            "apiKey": "sk-test-123",
        }
    )

    assert added["id"] == "my-gateway"
    assert added["configured"] is True
    assert added["editable"] is True
    assert "sk-test-123" not in json.dumps(added)
    assert "my-gateway" in model_ids()


def test_the_key_is_written_to_env_and_not_to_the_registry(registry):
    coach_llm.add_model(
        {
            "name": "My Gateway",
            "model": "gpt-4o-mini",
            "apiBase": "https://api.example.com/v1",
            "apiKey": "sk-test-123",
        }
    )

    env_text = (registry / ".env").read_text(encoding="utf-8")
    registry_text = (registry / "models.local.json").read_text(encoding="utf-8")

    assert "COACH_MODEL_MY_GATEWAY_KEY=sk-test-123" in env_text
    assert "sk-test-123" not in registry_text
    assert "COACH_MODEL_MY_GATEWAY_KEY" in registry_text


def test_a_local_endpoint_needs_no_key(registry):
    added = coach_llm.add_model(
        {
            "name": "Local Ollama",
            "model": "llama3",
            "apiBase": "http://127.0.0.1:11434/v1",
        }
    )

    assert added["configured"] is True
    assert not (registry / ".env").exists()


def test_an_existing_key_line_is_replaced_not_duplicated(registry):
    for value in ("first", "second"):
        coach_llm.add_model(
            {
                "name": "My Gateway",
                "model": "gpt-4o-mini",
                "apiBase": "https://api.example.com/v1",
                "apiKey": value,
            }
        )

    env_text = (registry / ".env").read_text(encoding="utf-8")

    assert env_text.count("COACH_MODEL_MY_GATEWAY_KEY=") == 1
    assert env_text.strip().endswith("=second")


def test_ids_do_not_collide(registry):
    for _ in range(3):
        coach_llm.add_model(
            {
                "name": "Same name",
                "model": "m",
                "apiBase": "http://127.0.0.1:1234/v1",
            }
        )

    assert {"same-name", "same-name-2", "same-name-3"} <= set(model_ids())


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "model": "m", "apiBase": "https://a.example/v1"},
        {"name": "x", "model": "", "apiBase": "https://a.example/v1"},
        {"name": "x", "model": "m", "apiBase": "ftp://a.example"},
        {"name": "x", "model": "m", "apiBase": "not-a-url"},
    ],
)
def test_invalid_input_is_rejected(registry, payload):
    with pytest.raises(ValueError):
        coach_llm.add_model(payload)


def test_a_shipped_model_cannot_be_removed(registry):
    assert coach_llm.remove_model("shipped") is False
    assert "shipped" in model_ids()


def test_a_model_added_from_the_ui_can_be_removed(registry):
    coach_llm.add_model(
        {"name": "Temp", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"}
    )

    assert coach_llm.remove_model("temp") is True
    assert "temp" not in model_ids()


def test_the_ui_can_see_which_models_are_editable(registry):
    coach_llm.add_model(
        {"name": "Temp", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"}
    )

    editable = {m["id"]: m["editable"] for m in coach_llm.list_models()}

    assert editable["shipped"] is False
    assert editable["temp"] is True
