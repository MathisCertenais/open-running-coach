"""Proxy adapter: ``opencode run --format json`` in a throwaway workspace.

Verified against opencode 2.1.4 on this machine:

- ``--standalone``, ``--format json``, ``--agent`` and ``-m provider/model``
  all exist (``opencode run --help``).
- The V2 config key is ``agents``; each entry accepts ``system``, ``steps``,
  ``mode`` and a ``permissions`` ruleset of
  ``{action, resource, effect}`` (``https://opencode.ai/config.json``).
  ``--agent <unknown>`` fails with ``Agent not found``, so the flag is real.
- ``--format json`` prints one JSON object per line. Observed event types:
  ``step_start``, ``text`` and ``error``. The SDK declares ``step-finish``
  parts carrying ``reason``, ``cost`` and ``tokens``; a local Ollama run did
  not emit one, so usage is reported as unknown when it is absent rather than
  invented.
- The config file is passed explicitly through ``OPENCODE_CONFIG`` and the cwd
  is a throwaway directory. Discovery from a system temp cwd worked in
  ``debug config`` but agent resolution returned ``Agent not found`` on macOS;
  the explicit path is the reliable form. Global ``~/.config/opencode/``
  credentials still load, and global instructions may still be prepended.
- The CLI cannot set this app's temperature or max_tokens and cannot call its
  Python tools, so every answer here is ``fidelity="proxy"``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Callable, Optional

from app import coach_llm

from .. import config
from .base import (
    Availability,
    AvailabilityStatus,
    Completion,
    ErrorKind,
    ModelSpec,
    Request,
    Status,
    ToolCall,
    Usage,
)

_STEP_FINISH_TYPES = {"step_finish", "step-finish"}
_TOOL_TYPES = {"tool_use", "tool"}
_MAX_PREVIEW = config.CLI_STDERR_TAIL_CHARS


@dataclass
class ParsedEvents:
    """What one JSONL transcript contained, before status is decided."""

    text: str = ""
    reasoning: bool = False
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Optional[Usage] = None
    cost_usd: Optional[float] = None
    finish_reason: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    event_types: dict[str, int] = field(default_factory=dict)
    raw_lines: list[str] = field(default_factory=list)


def model_reference(spec: ModelSpec) -> str:
    """Build ``provider/model[#variant]`` for ``-m``."""
    reference = f"{spec.origin}/{spec.model}"
    if spec.variant:
        reference = f"{reference}#{spec.variant}"
    return reference


def agent_config(system_prompt: str) -> dict:
    """The generated config: production prompt, one step, no tools."""
    return {
        "$schema": config.OPENCODE_CONFIG_SCHEMA,
        "agents": {
            config.OPENCODE_AGENT_NAME: {
                "description": "Benchmark agent: coach system prompt, no tools",
                "mode": "primary",
                "steps": config.OPENCODE_AGENT_STEPS,
                "system": system_prompt,
                "permissions": [dict(rule) for rule in config.OPENCODE_DENY_ALL],
            }
        },
    }


def write_workspace(directory: Path, system_prompt: str) -> Path:
    """Write ``opencode.jsonc`` into the throwaway cwd and return its path."""
    config_path = directory / config.OPENCODE_CONFIG_FILENAME
    config_path.write_text(
        json.dumps(agent_config(system_prompt), indent=2) + "\n",
        encoding="utf-8",
    )
    return config_path


def build_command(spec: ModelSpec, prompt: str, binary: str) -> list[str]:
    """The exact argv used for one CLI call."""
    return [
        binary,
        "run",
        "--standalone",
        "--format",
        "json",
        "--agent",
        config.OPENCODE_AGENT_NAME,
        "-m",
        model_reference(spec),
        "--",
        prompt,
    ]


def _as_mapping(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _tool_call(event: dict) -> Optional[ToolCall]:
    part = _as_mapping(event.get("part"))
    state = _as_mapping(part.get("state"))
    name = part.get("tool") or part.get("name") or ""
    if not name:
        return None
    arguments = _as_mapping(
        state.get("input") or part.get("input") or part.get("arguments")
    )
    output = state.get("output")
    if isinstance(output, dict):
        result = output
    elif output is None:
        result = _as_mapping(
            state.get("metadata") or part.get("result") or part.get("output")
        )
    else:
        result = {"output": str(output)}
    return ToolCall(
        round=1,
        name=str(name),
        arguments=arguments,
        result=result,
        ok=state.get("status") != "error",
    )


def _finish_reason(reason: object) -> Optional[str]:
    if not isinstance(reason, str) or not reason:
        return None
    lowered = reason.lower()
    if "length" in lowered or "max" in lowered:
        return "length"
    if "stop" in lowered or "end" in lowered or "complete" in lowered:
        return "stop"
    return reason


def _error_message(event: dict) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error)
    return str(event.get("message") or error or "opencode reported an error")


def parse_events(stdout: str) -> ParsedEvents:
    """Turn the JSONL event stream into text, tools, usage and failures."""
    parsed = ParsedEvents()
    text_parts: list[str] = []
    prompt_tokens = completion_tokens = total_tokens = 0
    saw_usage = False
    cost = 0.0
    saw_cost = False

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed.raw_lines.append(stripped)
        try:
            event = json.loads(stripped)
        except ValueError:
            parsed.parse_errors.append(stripped[:_MAX_PREVIEW])
            continue
        if not isinstance(event, dict):
            parsed.parse_errors.append(stripped[:_MAX_PREVIEW])
            continue

        event_type = str(event.get("type") or "unknown")
        parsed.event_types[event_type] = parsed.event_types.get(event_type, 0) + 1
        part = _as_mapping(event.get("part"))

        if event_type == "text":
            text = part.get("text") or event.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif event_type == "reasoning":
            parsed.reasoning = True
        elif event_type in _TOOL_TYPES:
            call = _tool_call(event)
            if call is not None:
                parsed.tool_calls.append(call)
        elif event_type in _STEP_FINISH_TYPES:
            tokens = _as_mapping(part.get("tokens") or event.get("tokens"))
            if tokens:
                saw_usage = True
                prompt_tokens += int(tokens.get("input") or 0)
                completion_tokens += int(tokens.get("output") or 0) + int(
                    tokens.get("reasoning") or 0
                )
                total_tokens += int(
                    tokens.get("total")
                    or (
                        int(tokens.get("input") or 0)
                        + int(tokens.get("output") or 0)
                        + int(tokens.get("reasoning") or 0)
                    )
                )
            step_cost = part.get("cost", event.get("cost"))
            if isinstance(step_cost, (int, float)):
                saw_cost = True
                cost += float(step_cost)
            reason = _finish_reason(part.get("reason") or event.get("reason"))
            if reason:
                parsed.finish_reason = reason
        elif event_type == "error":
            parsed.errors.append(_error_message(event))

    parsed.text = "".join(text_parts).strip()
    if saw_usage:
        parsed.usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            source="opencode_cli",
        )
    if saw_cost:
        parsed.cost_usd = round(cost, 6)
    return parsed


class OpenCodeCLIProvider:
    """Run the production coach prompt through the opencode CLI."""

    adapter = "opencode_cli"

    def __init__(
        self,
        binary: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        work_root: Path | None = None,
    ) -> None:
        self.binary = (
            binary
            or os.environ.get(config.OPENCODE_BIN_ENV)
            or config.OPENCODE_BIN_DEFAULT
        )
        self._runner = runner or subprocess.run
        self.work_root = work_root or config.DATA_ROOT

    def availability(self, spec: ModelSpec) -> Availability:
        """The CLI can run when the binary is on PATH and the entry is enabled."""
        if not spec.enabled:
            return Availability(
                AvailabilityStatus.DISABLED,
                spec.disabled_reason or "disabled in the roster",
            )
        if not spec.model:
            return Availability(
                AvailabilityStatus.UNKNOWN_ID, "no model name in the roster"
            )
        if shutil.which(self.binary) is None:
            return Availability(
                AvailabilityStatus.BINARY_MISSING,
                f"{self.binary!r} is not on PATH",
            )
        return Availability(AvailabilityStatus.OK)

    def complete(self, request: Request) -> Completion:
        """Run one CLI call and parse its JSONL transcript."""
        started = perf_counter()
        payload, truncated = coach_llm.snapshot_payload(dict(request.snapshot))
        prompt = f"{payload}\n\n{request.user_message}"
        command = build_command(request.model, prompt, self.binary)
        notes = [
            "athlete_data_in_user_turn",
            "possible_global_instructions",
            "possible_wrapper_text",
            "temperature_provider_default",
        ]
        if truncated:
            notes.append("context_truncated")

        with tempfile.TemporaryDirectory(prefix="coach-bench-") as workdir:
            config_root = self.work_root / config.TMP_DIRNAME
            config_root.mkdir(parents=True, exist_ok=True)
            config_directory = Path(
                tempfile.mkdtemp(prefix="opencode-config-", dir=config_root)
            )
            try:
                # The cwd carries the generated config as the spec describes;
                # it is also passed explicitly because discovery from a system
                # temp directory did not resolve the agent reliably on macOS.
                write_workspace(Path(workdir), coach_llm.SYSTEM_PROMPT)
                config_path = write_workspace(config_directory, coach_llm.SYSTEM_PROMPT)
                environment = os.environ.copy()
                environment["OPENCODE_CONFIG"] = str(config_path)
                try:
                    completed = self._runner(
                        command,
                        cwd=workdir,
                        capture_output=True,
                        text=True,
                        timeout=request.timeout_s,
                        env=environment,
                    )
                except subprocess.TimeoutExpired:
                    return Completion(
                        text="",
                        status=Status.TIMEOUT,
                        error_kind=ErrorKind.TIMEOUT,
                        error_message=("opencode did not finish before the timeout"),
                        latency_ms=int((perf_counter() - started) * 1000),
                        latency_kind="cli_process",
                        fidelity="proxy",
                        notes=tuple(notes),
                        context={"chars": len(payload), "truncated": truncated},
                    )
                except FileNotFoundError as exc:
                    return Completion(
                        text="",
                        status=Status.ERROR,
                        error_kind=ErrorKind.UNREACHABLE,
                        error_message=f"could not start {self.binary!r}: {exc}",
                        latency_ms=int((perf_counter() - started) * 1000),
                        latency_kind="cli_process",
                        fidelity="proxy",
                        notes=tuple(notes),
                        context={"chars": len(payload), "truncated": truncated},
                    )
            finally:
                shutil.rmtree(config_directory, ignore_errors=True)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        parsed = parse_events(stdout)
        latency_ms = int((perf_counter() - started) * 1000)
        diagnostics = {
            "exit_code": completed.returncode,
            "event_types": parsed.event_types,
            "stderr_tail": stderr[-_MAX_PREVIEW:],
            "model_reference": model_reference(request.model),
            "raw_events": parsed.raw_lines,
        }
        base = {
            "latency_ms": latency_ms,
            "latency_kind": "cli_process",
            "fidelity": "proxy",
            "notes": tuple(notes),
            "diagnostics": diagnostics,
            "context": {"chars": len(payload), "truncated": truncated},
            "tool_calls": tuple(parsed.tool_calls),
            "usage": parsed.usage or Usage(source="unknown"),
            "cost_usd": parsed.cost_usd,
            "cost_source": "opencode_cli" if parsed.cost_usd is not None else None,
            "finish_reason": parsed.finish_reason,
        }

        if completed.returncode != 0:
            message = (parsed.errors[0] if parsed.errors else "") or (
                stderr.strip()[-_MAX_PREVIEW:]
                or f"opencode exited {completed.returncode}"
            )
            return Completion(
                text="",
                status=Status.ERROR,
                error_kind=ErrorKind.CLI_EXIT,
                error_message=message,
                **base,
            )
        if parsed.errors:
            return Completion(
                text="",
                status=Status.ERROR,
                error_kind=ErrorKind.CLI_EXIT,
                error_message=parsed.errors[0],
                **base,
            )
        if not parsed.text:
            # Keep the three empty diagnoses apart: a model that spent its
            # budget on reasoning, a model cut off by the output cap, and a
            # genuinely empty response have different fixes. The pilot's three
            # ``empty`` rows were undiagnosable because they all collapsed here.
            if parsed.finish_reason == "length":
                kind = ErrorKind.OUTPUT_LENGTH
                message = (
                    "opencode reported step_finish reason=length and produced no "
                    "visible text (the output cap was consumed before the answer)"
                )
            elif parsed.reasoning:
                kind = ErrorKind.THINKING_ONLY
                message = "opencode produced only reasoning events and no visible text"
            elif parsed.parse_errors:
                kind = ErrorKind.CLI_PARSE
                message = parsed.parse_errors[0]
            else:
                kind = ErrorKind.EMPTY
                message = "opencode produced no visible text"
            return Completion(
                text="",
                status=Status.EMPTY,
                error_kind=kind,
                error_message=message,
                **base,
            )
        return Completion(text=parsed.text, status=Status.OK, **base)
