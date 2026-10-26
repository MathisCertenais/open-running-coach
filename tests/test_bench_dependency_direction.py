"""Dependency direction: ``bench`` may import ``app``; ``app`` may not import ``bench``."""

from __future__ import annotations

import re

from bench import config

_IMPORT = re.compile(r"^\s*(?:from|import)\s+bench\b", re.MULTILINE)


def test_app_never_imports_bench():
    offenders = []
    for path in (config.REPO_ROOT / "app").rglob("*.py"):
        if _IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(config.REPO_ROOT).as_posix())

    assert offenders == []
