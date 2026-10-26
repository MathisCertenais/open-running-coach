"""Provider adapters: production mapping and CLI transcript parsing."""

from __future__ import annotations

import json
import subprocess

from app import coach_llm
from bench.providers import opencode_cli
from bench.providers.base import (
    ErrorKind,
    Pricing,
    Request,
    Status,
    ToolCall,
)
from bench.providers.openai_http import OpenAIHTTPProvider
from bench.providers.opencode_cli import OpenCodeCLIProvider
from tests.bench_helpers import make_spec


def _request(spec, *, timeout_s=60.0, snapshot=None, tool_context=None):
    return Request(
        model=spec,
        snapshot=snapshot or {"load": {"last_7d": 100}},
        user_message="What should I do this week?",
        tool_context=tool_context if tool_context is not None else {"activities": []},
        timeout_s=timeout_s,
    )


def test_bench_openai_adapter_maps_trace(monkeypatch):
    spec = make_spec(
        "gemma",
        adapter="openai_http",
        registry_id="gemma-4-31b",
        origin="ragarenn",
        model="ilaas/gemma-4-31b",
        pricing=Pricing(1.0, 2.0),
    )
    trace = coach_llm.ChatTrace(
        text="A grounded answer.",
        tool_calls=(
            coach_llm.ToolCallRecord(
                round=1,
                name="search_activities",
                arguments={"limit": 5},
                result={"matched": 2},
            ),
        ),
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        },
        rounds=2,
        tools_offered=11,
        tools_dropped=False,
        finish_reason="stop",
        context_chars=500,
        context_truncated=False,
    )
    monkeypatch.setattr(coach_llm, "run_chat", lambda *args, **kwargs: trace)

    completion = OpenAIHTTPProvider().complete(_request(spec))

    assert completion.status == Status.OK
    assert completion.text == "A grounded answer."
    assert completion.fidelity == "production"
    assert completion.latency_kind == "http_roundtrip"
    assert completion.finish_reason == "stop"
    assert completion.usage.prompt_tokens == 100
    assert completion.usage.completion_tokens == 20
    assert completion.usage.source == "provider"
    assert completion.cost_usd == 0.00014
    assert completion.cost_source.startswith("price_table:")
    assert completion.context == {"chars": 500, "truncated": False}
    assert completion.diagnostics["tools_offered"] == 11
    assert completion.tool_calls == (
        ToolCall(
            round=1,
            name="search_activities",
            arguments={"limit": 5},
            result={"matched": 2},
            ok=True,
        ),
    )


def test_bench_openai_adapter_passes_registry_params(monkeypatch):
    spec = make_spec(
        "ollama",
        adapter="openai_http",
        registry_id="ollama-local",
        origin="ollama",
        model="qwen2.5:7b-instruct",
    )
    seen = {}

    def fake_run_chat(snapshot, history, user_message, model, tool_context=None):
        seen.update(model=model, history=history, tool_context=tool_context)
        return coach_llm.ChatTrace(
            text="ok",
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

    OpenAIHTTPProvider().complete(_request(spec, timeout_s=5.0))

    registry = coach_llm.find_model("ollama-local")
    assert seen["model"]["temperature"] == registry["temperature"]
    assert seen["model"]["max_tokens"] == registry["max_tokens"]
    assert seen["model"]["tools"] == registry["tools"]
    assert seen["model"]["timeout_s"] == 5.0
    assert seen["history"] == []


def test_bench_openai_adapter_classifies_errors(monkeypatch):
    spec = make_spec("m", adapter="openai_http", registry_id="ollama-local")

    def raise_with(message):
        def fake(*args, **kwargs):
            raise coach_llm.LLMError(message)

        return fake

    monkeypatch.setattr(coach_llm, "run_chat", raise_with("M returned HTTP 401: nope"))
    auth = OpenAIHTTPProvider().complete(_request(spec))
    assert auth.status == Status.ERROR
    assert auth.error_kind == ErrorKind.AUTH

    monkeypatch.setattr(
        coach_llm, "run_chat", raise_with("M returned an empty response.")
    )
    empty = OpenAIHTTPProvider().complete(_request(spec))
    assert empty.status == Status.EMPTY
    assert empty.error_kind == ErrorKind.EMPTY

    monkeypatch.setattr(
        coach_llm,
        "run_chat",
        raise_with("M returned only hidden reasoning (it is a thinking model)."),
    )
    thinking = OpenAIHTTPProvider().complete(_request(spec))
    assert thinking.error_kind == ErrorKind.THINKING_ONLY


class _Runner:
    """Stub for ``subprocess.run`` that records argv and cwd."""

    def __init__(self, *, stdout="", stderr="", returncode=0, raises=None):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.raises = raises
        self.command = None
        self.cwd = None
        self.workspace = None
        self.environment = None
        self.config_document = None

    def __call__(self, command, **kwargs):
        self.command = command
        self.cwd = kwargs["cwd"]
        self.workspace = sorted(
            p.name for p in __import__("pathlib").Path(kwargs["cwd"]).iterdir()
        )
        self.environment = kwargs["env"]
        config_path = self.environment.get("OPENCODE_CONFIG")
        if config_path:
            self.config_document = json.loads(
                __import__("pathlib").Path(config_path).read_text(encoding="utf-8")
            )
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(
            command, self.returncode, self.stdout, self.stderr
        )


def test_bench_cli_adapter_parses_events(tmp_path):
    events = [
        {"type": "step_start", "part": {}},
        {"type": "text", "part": {"text": "Hello "}},
        {"type": "text", "part": {"text": "world"}},
        {"type": "reasoning", "part": {"text": "hidden"}},
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "ls"},
                    "output": {"stdout": "x"},
                },
            },
        },
        {
            "type": "step_finish",
            "part": {
                "tokens": {
                    "input": 100,
                    "output": 20,
                    "reasoning": 5,
                    "cache": {"read": 0, "write": 0},
                },
                "cost": 0.0012,
                "reason": "length",
            },
        },
    ]
    stdout = "\n".join(json.dumps(event) for event in events) + "\n"
    runner = _Runner(stdout=stdout)
    provider = OpenCodeCLIProvider(binary="opencode", runner=runner, work_root=tmp_path)
    spec = make_spec(
        "cli",
        adapter="opencode_cli",
        origin="opencode-go",
        model="deepseek-v4.1-flash",
        cohort="proxy",
    )

    completion = provider.complete(_request(spec))

    assert completion.status == Status.OK
    assert completion.text == "Hello world"
    assert completion.fidelity == "proxy"
    assert completion.latency_kind == "cli_process"
    assert completion.usage.prompt_tokens == 100
    assert completion.usage.completion_tokens == 25
    assert completion.usage.total_tokens == 125
    assert completion.usage.source == "opencode_cli"
    assert completion.cost_usd == 0.0012
    assert completion.cost_source == "opencode_cli"
    assert completion.finish_reason == "length"
    assert completion.tool_calls[0].name == "bash"
    assert "athlete_data_in_user_turn" in completion.notes
    assert "possible_global_instructions" in completion.notes
    assert runner.workspace == ["opencode.jsonc"]
    assert runner.config_document["agents"]["coach-bench"]["system"] == (
        coach_llm.SYSTEM_PROMPT
    )
    assert runner.environment["OPENCODE_CONFIG"].endswith("opencode.jsonc")
    assert "--agent" in runner.command
    assert "opencode-go/deepseek-v4.1-flash" in runner.command


def test_bench_cli_adapter_timeout_and_exit(tmp_path):
    spec = make_spec(
        "cli", adapter="opencode_cli", origin="ollama", model="qwen2.5:7b-instruct"
    )
    timeout = OpenCodeCLIProvider(
        runner=_Runner(raises=subprocess.TimeoutExpired("opencode", 5)),
        work_root=tmp_path,
    ).complete(_request(spec))
    assert timeout.status == Status.TIMEOUT
    assert timeout.error_kind == ErrorKind.TIMEOUT

    exited = OpenCodeCLIProvider(
        runner=_Runner(returncode=2, stderr="permission denied"),
        work_root=tmp_path,
    ).complete(_request(spec))
    assert exited.status == Status.ERROR
    assert exited.error_kind == ErrorKind.CLI_EXIT
    assert "permission denied" in exited.error_message


def test_bench_cli_adapter_surfaces_error_event(tmp_path):
    stdout = json.dumps(
        {
            "type": "error",
            "error": {"type": "provider.no-route", "message": "Model unavailable"},
        }
    )
    spec = make_spec(
        "cli", adapter="opencode_cli", origin="ollama", model="qwen2.5:7b-instruct"
    )
    completion = OpenCodeCLIProvider(
        runner=_Runner(stdout=stdout), work_root=tmp_path
    ).complete(_request(spec))

    assert completion.status == Status.ERROR
    assert completion.error_kind == ErrorKind.CLI_EXIT
    assert completion.error_message == "Model unavailable"


def test_bench_cli_adapter_classifies_empty_kinds(tmp_path):
    """Length and reasoning-only empties are diagnoses, not one generic empty."""
    length_stdout = json.dumps(
        {"type": "step_finish", "part": {"reason": "length", "tokens": {}}}
    )
    spec = make_spec(
        "cli", adapter="opencode_cli", origin="ollama", model="qwen2.5:7b-instruct"
    )
    length = OpenCodeCLIProvider(
        runner=_Runner(stdout=length_stdout), work_root=tmp_path
    ).complete(_request(spec))
    assert length.status == Status.EMPTY
    assert length.error_kind == ErrorKind.OUTPUT_LENGTH
    assert "reason=length" in length.error_message

    reasoning_stdout = json.dumps(
        {"type": "reasoning", "part": {"text": "thinking only"}}
    )
    reasoning = OpenCodeCLIProvider(
        runner=_Runner(stdout=reasoning_stdout), work_root=tmp_path
    ).complete(_request(spec))
    assert reasoning.status == Status.EMPTY
    assert reasoning.error_kind == ErrorKind.THINKING_ONLY
    assert reasoning.error_kind != length.error_kind


def test_bench_cli_adapter_missing_binary():
    spec = make_spec(
        "cli", adapter="opencode_cli", origin="ollama", model="qwen2.5:7b-instruct"
    )
    result = OpenCodeCLIProvider(
        binary="definitely-not-an-opencode-binary"
    ).availability(spec)

    assert result.status.value == "binary_missing"


def test_bench_cli_agent_uses_production_prompt(tmp_path):
    config_path = opencode_cli.write_workspace(tmp_path, coach_llm.SYSTEM_PROMPT)
    document = json.loads(config_path.read_text(encoding="utf-8"))
    agent = document["agents"]["coach-bench"]

    assert agent["system"] == coach_llm.SYSTEM_PROMPT
    assert agent["steps"] == 1
    assert agent["mode"] == "primary"
    assert agent["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
    assert [path.name for path in tmp_path.iterdir()] == ["opencode.jsonc"]

    spec = make_spec(
        "cli",
        adapter="opencode_cli",
        origin="ragarenn",
        model="ilaas/gemma-4-31b",
        variant="thinking",
    )
    command = opencode_cli.build_command(spec, "prompt", "opencode")
    assert command == [
        "opencode",
        "run",
        "--standalone",
        "--format",
        "json",
        "--agent",
        "coach-bench",
        "-m",
        "ragarenn/ilaas/gemma-4-31b#thinking",
        "--",
        "prompt",
    ]
