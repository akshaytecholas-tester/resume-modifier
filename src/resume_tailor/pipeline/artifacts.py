"""Run directories and stage artifacts (spec-02 §4).

Each stage writes its artifact to `runs/<slug>/` before the next begins, so a
failed run resumes from the last completed stage rather than restarting from
the job description. With the Selector and Recall each reading the full corpus,
restarting a five-stage run because the Writer timed out would re-spend the two
most expensive calls for nothing.

`runs/` is disposable and gitignored (OQ-3). Nothing here is a source of truth:
everything is reproducible from `kb/` plus the posting.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

#: Stage name -> filename. Stage order is the pipeline order.
ARTIFACTS = {
    "posting": "posting.txt",
    "requirements": "requirements.json",
    "selection": "selection.json",
    "recall": "recall.json",
    "merged": "merged.json",
    "draft": "draft.json",
    "draft-previous": "draft-previous.json",
    "chat": "chat.jsonl",
    "validation": "validation.json",
    "gaps": "gaps.json",
    "usage": "usage.json",
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_length: int = 48) -> str:
    """Lowercase ASCII slug. Lowercase is not cosmetic — APFS is
    case-insensitive, so `Acme` and `acme` must not become two directories."""
    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")
    return slug[:max_length].strip("-") or "run"


def run_slug(role: str | None, company: str | None = None, on: date | None = None) -> str:
    parts = [(on or date.today()).isoformat()]
    if company:
        parts.append(slugify(company, max_length=24))
    parts.append(slugify(role or "untitled", max_length=36))
    return "-".join(parts)


@dataclass
class Run:
    """One tailoring attempt on disk."""

    directory: Path

    @property
    def id(self) -> str:
        return self.directory.name

    @classmethod
    def create(cls, runs_dir: Path, slug: str) -> Run:
        """Make a fresh run directory, suffixing on collision.

        Never reuses a directory: a second attempt at the same posting on the
        same day is a separate run, and silently overwriting the first would
        destroy the comparison that makes a re-run worth doing.
        """
        directory = runs_dir / slug
        suffix = 2
        while directory.exists():
            directory = runs_dir / f"{slug}-{suffix}"
            suffix += 1
        directory.mkdir(parents=True)
        return cls(directory)

    def path(self, stage: str) -> Path:
        try:
            return self.directory / ARTIFACTS[stage]
        except KeyError:
            known = ", ".join(ARTIFACTS)
            raise ValueError(f"unknown stage {stage!r}; expected one of: {known}") from None

    def has(self, stage: str) -> bool:
        path = self.path(stage)
        return path.is_file() and path.stat().st_size > 0

    def write(self, stage: str, data: Any) -> Path:
        """Write atomically, so an interrupted run cannot leave a truncated
        artifact that the resume path then reads as complete."""
        path = self.path(stage)
        text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path

    def read(self, stage: str) -> Any:
        path = self.path(stage)
        text = path.read_text(encoding="utf-8")
        return text if path.suffix == ".txt" else json.loads(text)

    def completed_stages(self) -> list[str]:
        return [stage for stage in ARTIFACTS if self.has(stage)]


def list_runs(runs_dir: Path) -> list[Run]:
    """Newest first, by directory name — which sorts correctly because the
    slug leads with an ISO date."""
    if not runs_dir.is_dir():
        return []
    return [Run(p) for p in sorted(runs_dir.iterdir(), reverse=True) if p.is_dir()]
