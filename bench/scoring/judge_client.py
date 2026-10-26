"""Judge transport: one protocol, one OpenAI-compatible adapter, one fake.

The judge is not a model under test, so it never goes through the roster or a
provider adapter. It still must not invent its own HTTP call: the transport
reuses ``coach_llm._send`` and ``coach_llm._content``, which is the same
OpenAI-compatible path the production coach uses. That keeps the request shape
(one system message, one user message, no tools) in one place.

A judge model that is not in the app registry is registered with
``--judge-base-url/--judge-model/--judge-key-env``; nothing here reads the
roster.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Protocol, Sequence

from app import coach_llm

from .. import config
from ..providers.resilience import (
    Pacer,
    RetryPolicy,
    call_with_retry,
    retry_after,
    retry_reason,
)


@dataclass(frozen=True)
class JudgeReply:
    """One judge turn as the transport saw it, not just its visible text.

    ``reasoning_chars`` is what makes the reasoning-only failure observable:
    an empty ``text`` with reasoning or a ``length`` finish means the budget
    went to hidden tokens, which is a transport problem to retry, not an
    invalid verdict.
    """

    text: str
    finish_reason: Optional[str] = None
    reasoning_chars: int = 0
    usage: Optional[Mapping[str, object]] = None
    max_tokens: int = 0

    @property
    def reasoning_only(self) -> bool:
        """True when the turn produced no visible text and burned the budget."""
        if self.text.strip():
            return False
        return bool(self.reasoning_chars) or self.finish_reason == "length"


class JudgeClient(Protocol):
    """The one thing the judge loop needs from a transport."""

    model_id: str

    def complete(
        self, system: str, user: str, *, max_tokens: Optional[int] = None
    ) -> JudgeReply:
        """Return the reply. Raise on a transport failure."""
        ...


def _visible_text(message: Mapping[str, object]) -> tuple[str, int]:
    """Visible content and the length of any hidden reasoning.

    The production ``_content`` raises on empty/thinking-only replies, which
    loses the finish reason the judge needs. This is the non-raising version.
    """
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    text = content.strip() if isinstance(content, str) else ""
    reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
    reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    return text, reasoning_chars


def split_base_url(base_url: str) -> tuple[str, str]:
    """Split a full chat-completions URL into ``(base_url, chat_path)``.

    Accepts both ``https://host/v1`` and
    ``https://host/v1/chat/completions`` so a user can paste the URL the
    provider documents.
    """
    cleaned = base_url.rstrip("/")
    if cleaned.endswith(config.JUDGE_CHAT_PATH):
        return cleaned[: -len(config.JUDGE_CHAT_PATH)], config.JUDGE_CHAT_PATH
    return cleaned, config.JUDGE_CHAT_PATH


@dataclass(frozen=True)
class OpenAICompatibleJudgeClient:
    """Judge calls over ``coach_llm._send``, with no tools and temperature 0."""

    model_id: str
    base_url: str
    model: str | None = None
    api_key: str | None = None
    key_env: str | None = None
    timeout_s: float = config.JUDGE_DEFAULT_TIMEOUT_S
    temperature: float = config.JUDGE_TEMPERATURE
    max_tokens: int = config.JUDGE_MAX_TOKENS
    # Albert allows 10 requests/minute on this endpoint; every turn (including
    # a retry) waits for the pacer. Clock and sleep are injectable so tests
    # never sleep for real.
    min_interval_s: float = config.JUDGE_MIN_INTERVAL_S
    clock: Callable[[], float] = field(
        default=time.monotonic, repr=False, compare=False
    )
    sleep: Callable[[float], None] = field(
        default=time.sleep, repr=False, compare=False
    )
    rng: Callable[[float, float], float] = field(
        default=random.uniform, repr=False, compare=False
    )
    _registry: dict = field(init=False, repr=False, compare=False)
    _pacer: Pacer = field(init=False, repr=False, compare=False)
    _retry: RetryPolicy = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        base, chat_path = split_base_url(self.base_url)
        key = self.api_key
        if not key and self.key_env:
            key = os.environ.get(self.key_env)
        registry = {
            "id": self.model_id,
            "name": self.model_id,
            "base_url": base,
            "chat_path": chat_path,
            "model": self.model or self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "api_key": key or "",
            "timeout_s": self.timeout_s,
        }
        object.__setattr__(self, "_registry", registry)
        object.__setattr__(
            self,
            "_pacer",
            Pacer(self.min_interval_s, clock=self.clock, sleep=self.sleep),
        )
        object.__setattr__(
            self,
            "_retry",
            RetryPolicy(
                max_attempts=config.JUDGE_RETRY_MAX_ATTEMPTS,
                base_delay_s=config.JUDGE_RETRY_BASE_DELAY_S,
                max_delay_s=config.JUDGE_RETRY_MAX_DELAY_S,
            ),
        )

    def complete(
        self, system: str, user: str, *, max_tokens: Optional[int] = None
    ) -> JudgeReply:
        """One judge turn: system prompt plus one JSON payload.

        ``max_tokens`` overrides the construction budget for this call, which is
        how the reasoning-only retry doubles it without rebuilding the client.
        """
        registry = dict(self._registry)
        registry["max_tokens"] = int(max_tokens or self.max_tokens)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        outcome = call_with_retry(
            lambda _remaining: coach_llm._send(registry, messages),
            policy=self._retry,
            clock=self.clock,
            sleep=self.sleep,
            retryable=retry_reason,
            retry_after=retry_after,
            budget_s=self.timeout_s,
            before_attempt=self._pacer.wait,
            rng=self.rng,
        )
        if outcome.error is not None:
            raise outcome.error
        result = outcome.value
        text, reasoning_chars = _visible_text(result.message)
        return JudgeReply(
            text=text,
            finish_reason=result.finish_reason,
            reasoning_chars=reasoning_chars,
            usage=result.usage,
            max_tokens=registry["max_tokens"],
        )


@dataclass
class FakeJudgeClient:
    """Deterministic judge double for tests; never touches the network.

    A reply may be a string, a ``JudgeReply`` (for reasoning-only or length
    cases) or a callable returning either.
    """

    replies: Sequence[str | JudgeReply | Callable[[str, str], object]]
    model_id: str = "fake-judge"
    calls: list[tuple[str, str]] = field(default_factory=list)
    budgets: list[int] = field(default_factory=list)
    _index: int = field(default=0, init=False, repr=False)

    def complete(
        self, system: str, user: str, *, max_tokens: Optional[int] = None
    ) -> JudgeReply:
        self.calls.append((system, user))
        self.budgets.append(int(max_tokens or 0))
        if self._index >= len(self.replies):
            raise RuntimeError("FakeJudgeClient ran out of replies")
        reply = self.replies[self._index]
        self._index += 1
        value = reply(system, user) if callable(reply) else reply
        if isinstance(value, JudgeReply):
            return value
        return JudgeReply(text=str(value), max_tokens=int(max_tokens or 0))
