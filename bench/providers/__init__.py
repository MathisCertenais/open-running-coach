"""Adapter registry.

Adding a transport means one module implementing ``Provider`` and one line
here; the runner, records and report never change.
"""

from __future__ import annotations

from .base import Provider
from .fake import FakeProvider
from .openai_http import OpenAIHTTPProvider
from .opencode_cli import OpenCodeCLIProvider

ADAPTERS: dict[str, Provider] = {
    OpenAIHTTPProvider.adapter: OpenAIHTTPProvider(),
    OpenCodeCLIProvider.adapter: OpenCodeCLIProvider(),
    FakeProvider.adapter: FakeProvider(),
}
