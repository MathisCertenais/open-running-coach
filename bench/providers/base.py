"""Provider protocol shared by the benchmark adapters.

The runner knows nothing about HTTP, headers, subprocesses or JSONL event
streams. It knows ``Provider``, and every adapter turns one of those transports
into the same ``Completion``. That is what lets a new endpoint be a roster line
instead of a change in the capture loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Mapping, Optional, Protocol


class Status(StrEnum):
    """Outcome of one request."""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    EMPTY = "empty"


class ErrorKind(StrEnum):
    """Why a request failed, in terms the report can group."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    NOT_FOUND = "not_found"
    SERVER = "server"
    TIMEOUT = "timeout"
    EMPTY = "empty"
    THINKING_ONLY = "thinking_only"
    # The model hit its output cap before writing visible text; distinct from a
    # provider that returned an empty body.
    OUTPUT_LENGTH = "output_length"
    CLI_EXIT = "cli_exit"
    CLI_PARSE = "cli_parse"
    UNREACHABLE = "unreachable"


class AvailabilityStatus(StrEnum):
    """Whether a roster entry can be called in this environment."""

    OK = "ok"
    MISSING_KEY = "missing_key"
    UNKNOWN_ID = "unknown_id"
    BINARY_MISSING = "binary_missing"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Availability:
    """Provider-specific answer to "can this model run here?"."""

    status: AvailabilityStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when the model can be called here."""
        return self.status is AvailabilityStatus.OK


@dataclass(frozen=True)
class Pricing:
    """Published price per million tokens, in US dollars."""

    input_per_mtok: float
    output_per_mtok: float

    def cost_usd(self, usage: "Usage") -> Optional[float]:
        """Return the estimated cost, or ``None`` when usage is incomplete."""
        if usage.prompt_tokens is None or usage.completion_tokens is None:
            return None
        cost = (
            usage.prompt_tokens / 1_000_000.0 * self.input_per_mtok
            + usage.completion_tokens / 1_000_000.0 * self.output_per_mtok
        )
        return round(cost, 6)


@dataclass(frozen=True)
class ModelSpec:
    """One roster line, resolved into what an adapter needs."""

    key: str
    adapter: str
    origin: str
    model: str
    variant: Optional[str] = None
    registry_id: Optional[str] = None
    # A roster may name its endpoint directly, for a model the app registry
    # does not carry. Registry entries leave these empty and resolve by id.
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    pricing: Optional[Pricing] = None
    cohort: Literal["production", "proxy"] = "production"
    params: Mapping[str, object] = field(default_factory=dict)
    enabled: bool = True
    label: Optional[str] = None
    # Why a disabled entry cannot measure the model, shown by ``providers`` and
    # the report. Kept out of ``signature()``: it never changes an answer.
    disabled_reason: Optional[str] = None

    def signature(self) -> dict:
        """Fields that must match for two sweeps to be comparable.

        Prices are deliberately excluded: a price-table update changes what a
        sweep costs, never what a model answered, so it must not invalidate
        stored answers.
        """
        return {
            "key": self.key,
            "adapter": self.adapter,
            "origin": self.origin,
            "model": self.model,
            "cohort": self.cohort,
            "variant": self.variant,
            "registry_id": self.registry_id,
            "base_url": self.base_url,
            "headers": dict(self.headers),
            "params": dict(self.params),
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class Usage:
    """Token counts as reported by the provider, not estimated by the harness."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    source: Literal["provider", "opencode_cli", "unknown"] = "unknown"

    @property
    def reported(self) -> bool:
        """True only when the provider supplied real token counts."""
        return (
            self.source != "unknown"
            and self.prompt_tokens is not None
            and self.completion_tokens is not None
        )


@dataclass(frozen=True)
class ToolCall:
    """One tool call a model made, with the result it was given."""

    round: int
    name: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]
    ok: bool = True


@dataclass(frozen=True)
class Request:
    """What to ask, not how to encode it: no HTTP or CLI shape escapes here."""

    model: ModelSpec
    snapshot: Mapping[str, object]
    user_message: str
    tool_context: Optional[Mapping[str, object]]
    timeout_s: float


@dataclass(frozen=True)
class Completion:
    """One answer, successful or not.

    ``complete()`` returns failures as data: a 401, a timeout or an empty body
    must not abort a sweep. Only programmer error raises.
    """

    text: str
    status: Status
    error_kind: Optional[ErrorKind] = None
    error_message: Optional[str] = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    cost_usd: Optional[float] = None
    latency_ms: int = 0
    latency_kind: Literal["http_roundtrip", "cli_process"] = "http_roundtrip"
    fidelity: Literal["production", "proxy"] = "production"
    notes: tuple[str, ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    context: Mapping[str, object] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    cost_source: Optional[str] = None


class Provider(Protocol):
    """Transport boundary: one roster adapter implements these two methods."""

    adapter: str

    def availability(self, spec: ModelSpec) -> Availability:
        """Report whether this model can be called in the current environment."""
        ...

    def complete(self, request: Request) -> Completion:
        """Produce one completion, converting model failures into ``Completion``."""
        ...
