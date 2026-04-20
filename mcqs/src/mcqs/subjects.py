"""Subject discovery — one top-level directory under docs-bundle = one subject."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_IGNORED = {
    ".git",
    ".tools",
    "__pycache__",
    "node_modules",
}


@dataclass(frozen=True)
class Subject:
    slug: str
    title: str
    docs_root: Path


def _title_from_slug(slug: str) -> str:
    # `spring-boot-4` → `Spring Boot 4`, `yt-saudi-fintech` → `YT Saudi Fintech`.
    parts = re.split(r"[-_]+", slug)
    return " ".join(p.upper() if len(p) <= 2 else p.capitalize() for p in parts)


def discover(root: Path) -> list[Subject]:
    """Every non-hidden top-level directory becomes a subject."""
    if not root.exists():
        raise FileNotFoundError(f"docs_bundle_root not found: {root}")
    out: list[Subject] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in _IGNORED:
            continue
        out.append(Subject(slug=entry.name, title=_title_from_slug(entry.name), docs_root=entry))
    return out
