"""Test double: deterministic completions with no network and no subprocess."""

from __future__ import annotations

from typing import Callable, Mapping

from .base import (
    Availability,
    AvailabilityStatus,
    Completion,
    ModelSpec,
    Request,
    Status,
    Usage,
)


class FakeProvider:
    """A provider whose answers are declared by the test.

    ``responses`` maps a model key to a ``Completion`` or to a callable that
    receives the ``Request``. A key in ``raise_for`` raises instead, which is
    how the capture loop's isolation is tested without special-casing the
    provider inside the loop.
    """

    adapter = "fake"

    def __init__(
        self,
        responses: Mapping[str, Completion | Callable[[Request], Completion]]
        | None = None,
        *,
        default: Completion | None = None,
        availability: Availability | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.default = default or Completion(
            text="Fake answer.",
            status=Status.OK,
            usage=Usage(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                source="provider",
            ),
            context={"chars": 10, "truncated": False},
            diagnostics={"tools_offered": 0},
            finish_reason="stop",
        )
        self.availability_result = availability or Availability(AvailabilityStatus.OK)
        self.raise_for = set(raise_for or ())
        self.requests: list[Request] = []

    def availability(self, spec: ModelSpec) -> Availability:
        """Return the availability the test declared."""
        return self.availability_result

    def complete(self, request: Request) -> Completion:
        """Return the scripted answer, or raise if the test asked for that."""
        self.requests.append(request)
        if request.model.key in self.raise_for:
            raise RuntimeError(f"fake provider failure for {request.model.key}")
        response = self.responses.get(request.model.key, self.default)
        return response(request) if callable(response) else response
