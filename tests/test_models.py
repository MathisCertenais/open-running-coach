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
    assert added["source"] == "local"
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


def test_a_shipped_model_is_hidden_rather_than_rewritten(registry):
    before = (registry / "models.json").read_text("utf-8")

    assert coach_llm.remove_model("shipped") is True
    assert "shipped" not in model_ids()
    assert (registry / "models.json").read_text("utf-8") == before
    assert coach_llm.hidden_model_ids() == ["shipped"]
    stored = json.loads((registry / "models.local.json").read_text("utf-8"))
    assert stored["hidden"] == ["shipped"]


def test_deleting_a_shipped_model_keeps_its_shared_key(registry):
    coach_llm.remove_model("shipped")

    assert not _key_file(registry).exists()

    assert coach_llm.restore_hidden_models() == 1
    assert "shipped" in model_ids()
    assert coach_llm.MODELS[0]["api_key"] == "shipped-secret"


def test_deleting_an_unknown_model_is_false(registry):
    assert coach_llm.remove_model("nope") is False


def test_deleting_an_override_hides_the_shipped_entry_too(registry):
    coach_llm.update_model(
        "shipped", {"name": "Mine", "model": "m", "apiBase": "https://a.example/v1"}
    )

    assert coach_llm.remove_model("shipped") is True
    assert "shipped" not in model_ids()
    stored = json.loads((registry / "models.local.json").read_text("utf-8"))
    assert stored["models"] == []
    assert stored["hidden"] == ["shipped"]


def test_added_models_survive_a_delete_and_restore_of_a_shipped_one(registry):
    coach_llm.remove_model("shipped")
    added = _add_gateway()

    assert model_ids() == [added["id"]]
    assert coach_llm.restore_hidden_models() == 1
    assert set(model_ids()) == {"shipped", added["id"]}
    assert coach_llm.hidden_model_ids() == []


def test_restoring_with_nothing_hidden_is_a_no_op(registry):
    assert coach_llm.restore_hidden_models() == 0


def test_hiding_the_default_model_falls_back_to_another_one(registry):
    coach_llm.add_model(
        {
            "name": "Backup",
            "model": "m",
            "apiBase": "https://api.example.com/v1",
            "apiKey": "sk-backup",
        }
    )
    assert coach_llm.default_model_id() == "shipped"

    coach_llm.remove_model("shipped")

    assert coach_llm.default_model_id() == "backup"
    assert coach_llm.llm_configured() is True


def test_a_model_added_from_the_ui_can_be_removed(registry):
    coach_llm.add_model(
        {"name": "Temp", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"}
    )

    assert coach_llm.remove_model("temp") is True
    assert "temp" not in model_ids()


def test_the_ui_can_see_where_each_model_comes_from(registry):
    coach_llm.add_model(
        {"name": "Temp", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"}
    )
    coach_llm.update_model(
        "shipped", {"name": "Mine", "model": "m", "apiBase": "https://a.example/v1"}
    )

    sources = {m["id"]: m["source"] for m in coach_llm.list_models()}

    assert sources["shipped"] == "override"
    assert sources["temp"] == "local"


def test_a_plain_shipped_model_is_reported_as_shipped(registry):
    assert {m["id"]: m["source"] for m in coach_llm.list_models()} == {"shipped": "shipped"}


def _key_file(tmp_path):
    return tmp_path / ".env"


def _add_gateway(api_key="sk-first"):
    return coach_llm.add_model(
        {
            "name": "My Gateway",
            "model": "gpt-4o-mini",
            "apiBase": "https://api.example.com/v1",
            "apiKey": api_key,
        }
    )


def test_the_public_list_carries_no_key_but_does_carry_the_endpoint(registry):
    _add_gateway()

    entry = next(m for m in coach_llm.list_models() if m["id"] == "my-gateway")

    assert entry["apiBase"] == "https://api.example.com/v1"
    assert entry["chatPath"] == "/chat/completions"
    assert "sk-first" not in json.dumps(entry)


def test_a_model_can_be_edited_without_resending_the_key(registry):
    added = _add_gateway()

    updated = coach_llm.update_model(
        added["id"],
        {
            "name": "My Gateway v2",
            "model": "gpt-4o",
            "apiBase": "https://gateway.example.com/v1",
        },
    )

    assert updated["id"] == added["id"]  # the id never changes
    assert updated["name"] == "My Gateway v2"
    assert updated["model"] == "gpt-4o"
    assert updated["apiBase"] == "https://gateway.example.com/v1"
    assert updated["configured"] is True
    assert "COACH_MODEL_MY_GATEWAY_KEY=sk-first" in _key_file(registry).read_text("utf-8")


def test_editing_rotates_the_key_in_place(registry):
    added = _add_gateway()

    coach_llm.update_model(
        added["id"],
        {
            "name": "My Gateway",
            "model": "gpt-4o-mini",
            "apiBase": "https://api.example.com/v1",
            "apiKey": "sk-second",
        },
    )

    env_text = _key_file(registry).read_text("utf-8")
    assert env_text.count("COACH_MODEL_MY_GATEWAY_KEY=") == 1
    assert "sk-second" in env_text
    assert "sk-first" not in env_text
    registry_text = (registry / "models.local.json").read_text("utf-8")
    assert "sk-second" not in registry_text


def test_editing_leaves_the_other_entries_alone(registry):
    first = _add_gateway()
    second = coach_llm.add_model(
        {"name": "Other", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"}
    )

    coach_llm.update_model(
        first["id"],
        {"name": "Renamed", "model": "m2", "apiBase": "http://127.0.0.1:1234/v1"},
    )

    assert {first["id"], second["id"]} <= set(model_ids())
    names = {m["id"]: m["name"] for m in coach_llm.list_models()}
    assert names[first["id"]] == "Renamed"
    assert names[second["id"]] == "Other"


def test_the_chat_path_can_be_cleared_when_editing(registry):
    added = coach_llm.add_model(
        {
            "name": "Gateway",
            "model": "m",
            "apiBase": "http://127.0.0.1:1234/v1",
            "chatPath": "/v1/chat/completions",
        }
    )

    updated = coach_llm.update_model(
        added["id"],
        {"name": "Gateway", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"},
    )

    assert updated["chatPath"] == "/chat/completions"


def test_a_shipped_model_is_edited_through_a_local_override(registry):
    before = (registry / "models.json").read_text("utf-8")

    updated = coach_llm.update_model(
        "shipped",
        {
            "name": "Shipped, but mine",
            "model": "other-model",
            "apiBase": "https://elsewhere.example/v1",
        },
    )

    assert updated["id"] == "shipped"
    assert updated["name"] == "Shipped, but mine"
    assert updated["apiBase"] == "https://elsewhere.example/v1"
    assert updated["source"] == "override"
    assert (registry / "models.json").read_text("utf-8") == before
    stored = json.loads((registry / "models.local.json").read_text("utf-8"))
    assert stored["models"][0]["id"] == "shipped"


def test_editing_a_shipped_model_keeps_its_shared_key(registry):
    updated = coach_llm.update_model(
        "shipped", {"name": "Shipped", "model": "m", "apiBase": "https://a.example/v1"}
    )

    assert updated["configured"] is True  # still reads SHIPPED_KEY
    overridden = json.loads((registry / "models.local.json").read_text("utf-8"))
    assert overridden["models"][0]["apiKeyEnv"] == "SHIPPED_KEY"
    assert not _key_file(registry).exists()


def test_a_new_key_on_a_shipped_model_does_not_clobber_the_shared_variable(registry):
    updated = coach_llm.update_model(
        "shipped",
        {
            "name": "Shipped",
            "model": "m",
            "apiBase": "https://a.example/v1",
            "apiKey": "sk-own",
        },
    )

    assert updated["configured"] is True
    env_text = _key_file(registry).read_text("utf-8")
    assert "COACH_MODEL_SHIPPED_KEY=sk-own" in env_text
    assert "SHIPPED_KEY=shipped-secret" not in env_text
    assert coach_llm.MODELS[0]["api_key"] == "sk-own"


def test_editing_an_unknown_model_returns_none(registry):
    assert (
        coach_llm.update_model(
            "nope", {"name": "x", "model": "m", "apiBase": "https://a.example/v1"}
        )
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "model": "m", "apiBase": "https://a.example/v1"},
        {"name": "x", "model": "", "apiBase": "https://a.example/v1"},
        {"name": "x", "model": "m", "apiBase": "ftp://a.example"},
    ],
)
def test_invalid_edits_are_rejected(registry, payload):
    added = _add_gateway()

    with pytest.raises(ValueError):
        coach_llm.update_model(added["id"], payload)


def test_removing_a_model_also_removes_its_key(registry):
    added = _add_gateway()
    assert "sk-first" in _key_file(registry).read_text("utf-8")

    assert coach_llm.remove_model(added["id"]) is True

    env_text = _key_file(registry).read_text("utf-8")
    assert "COACH_MODEL_MY_GATEWAY_KEY" not in env_text
    assert "sk-first" not in env_text


def test_removing_one_model_does_not_touch_another_models_key(registry):
    _add_gateway()
    coach_llm.add_model(
        {
            "name": "Second",
            "model": "m",
            "apiBase": "https://api.example.com/v1",
            "apiKey": "sk-second",
        }
    )

    coach_llm.remove_model("my-gateway")

    env_text = _key_file(registry).read_text("utf-8")
    assert "sk-first" not in env_text
    assert "COACH_MODEL_SECOND_KEY=sk-second" in env_text


def test_extra_headers_can_be_set_as_json_from_the_ui(registry):
    added = coach_llm.add_model(
        {
            "name": "OpenCode Go",
            "model": "m",
            "apiBase": "https://opencode.ai/inference/go/openai/v1",
            "headers": '{"x-opencode-session": "{session}"}',
        }
    )

    assert added["headers"] == {"x-opencode-session": "{session}"}
    stored = json.loads((registry / "models.local.json").read_text("utf-8"))
    assert stored["models"][0]["headers"] == {"x-opencode-session": "{session}"}


def test_headers_can_be_cleared_when_editing(registry):
    added = coach_llm.add_model(
        {
            "name": "Gateway",
            "model": "m",
            "apiBase": "http://127.0.0.1:1234/v1",
            "headers": {"x-opencode-session": "{session}"},
        }
    )

    updated = coach_llm.update_model(
        added["id"],
        {"name": "Gateway", "model": "m", "apiBase": "http://127.0.0.1:1234/v1"},
    )

    assert updated["headers"] == {}


def test_invalid_header_json_is_rejected(registry):
    with pytest.raises(ValueError):
        coach_llm.add_model(
            {
                "name": "Gateway",
                "model": "m",
                "apiBase": "http://127.0.0.1:1234/v1",
                "headers": "not json",
            }
        )


def test_a_secret_cannot_be_smuggled_into_the_authorization_header(registry):
    with pytest.raises(ValueError):
        coach_llm.add_model(
            {
                "name": "Gateway",
                "model": "m",
                "apiBase": "http://127.0.0.1:1234/v1",
                "headers": {"Authorization": "Bearer sk-leak"},
            }
        )
