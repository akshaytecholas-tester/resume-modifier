"""Reading `kb/` off disk into a corpus (spec-01 §1 P1).

Frontmatter is split by hand and parsed with ruamel rather than handed to
`python-frontmatter`, which parses through PyYAML and discards comments and key
order on the way back out. The `TODO: expand` comments the bootstrap leaves
behind are content, and a round trip that eats them is a silent loss.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import ENTRY_MODELS, TYPE_DIRS, BaseEntry, SkillDeclaration, TaxonomyTerm
from .yamlio import load_yaml, parse_yaml

DELIMITER = "---"

#: Stable corpus ordering. Agent prompts put the corpus first so it caches as a
#: prefix (spec-03 §6); any reordering changes the prefix bytes and silently
#: costs a full re-read on every call. Hence a fixed order, not dict order.
TYPE_ORDER = ("role", "fact", "project", "blog", "education", "certification", "award")


class ParseError(ValueError):
    """A file on disk is not a readable entry. Carries the path."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True)
class Entry:
    """One knowledge-base entry: validated frontmatter plus its body prose."""

    path: Path
    meta: BaseEntry
    body: str
    raw: str
    frontmatter: Any  # ruamel CommentedMap — kept for round-trip writes

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def type(self) -> str:
        return self.meta.type

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()

    def estimated_tokens(self) -> int:
        """Rough size for corpus statistics. **An estimate, not a count.**

        Chars/4 is close enough to track corpus growth against the OQ-2
        threshold. Real figures come from backend usage reporting, which is why
        no tokeniser dependency is pulled in for this.
        """
        return max(1, len(self.raw) // 4)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(yaml_text, body)`` for a `---`-delimited file."""
    if not text.startswith(DELIMITER):
        raise ValueError("file does not start with a '---' frontmatter delimiter")

    rest = text[len(DELIMITER) :]
    if rest.startswith("\n"):
        rest = rest[1:]
    elif rest.startswith("\r\n"):
        rest = rest[2:]

    marker = f"\n{DELIMITER}"
    end = rest.find(marker)
    while end != -1:
        after = rest[end + len(marker) :]
        if after == "" or after.startswith(("\n", "\r\n")):
            break
        end = rest.find(marker, end + 1)
    if end == -1:
        raise ValueError("frontmatter is never closed by a '---' line")

    yaml_text = rest[:end]
    body = rest[end + len(marker) :].lstrip("\r\n")
    return yaml_text, body


def parse_entry(path: Path, text: str | None = None) -> Entry:
    raw = path.read_text(encoding="utf-8") if text is None else text
    try:
        yaml_text, body = split_frontmatter(raw)
    except ValueError as exc:
        raise ParseError(path, str(exc)) from exc

    try:
        data = parse_yaml(yaml_text)
    except Exception as exc:
        raise ParseError(path, f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise ParseError(path, "frontmatter is not a mapping")

    entry_type = data.get("type")
    if entry_type not in ENTRY_MODELS:
        known = ", ".join(sorted(ENTRY_MODELS))
        raise ParseError(path, f"type {entry_type!r} is not one of: {known}")

    model = ENTRY_MODELS[entry_type]
    try:
        meta = model.model_validate(dict(data))
    except Exception as exc:
        raise ParseError(path, str(exc)) from exc

    return Entry(path=path, meta=meta, body=body, raw=raw, frontmatter=data)


@dataclass
class Corpus:
    """Everything in `kb/`, in a deterministic order."""

    root: Path
    entries: list[Entry] = field(default_factory=list)
    identity_path: Path | None = None
    taxonomy: dict[str, TaxonomyTerm] = field(default_factory=dict)
    skills: list[SkillDeclaration] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)

    def by_id(self) -> dict[str, Entry]:
        return {e.id: e for e in self.entries}

    def of_type(self, entry_type: str) -> list[Entry]:
        return [e for e in self.entries if e.type == entry_type]

    def facts_of(self, parent_id: str) -> list[Entry]:
        return [e for e in self.entries if e.type == "fact" and e.meta.parent == parent_id]

    def estimated_tokens(self) -> int:
        return sum(e.estimated_tokens() for e in self.entries)


def _sort_key(entry: Entry) -> tuple[int, str]:
    order = TYPE_ORDER.index(entry.type) if entry.type in TYPE_ORDER else len(TYPE_ORDER)
    return (order, entry.id)


def load_corpus(kb_dir: Path, *, strict: bool = False) -> Corpus:
    """Read every entry under `kb_dir`.

    With ``strict=False`` unreadable files are collected into
    ``parse_errors`` rather than raised, so `rt kb validate` can report every
    problem in one pass instead of one per run.
    """
    kb_dir = kb_dir.resolve()
    corpus = Corpus(root=kb_dir)

    for entry_type in TYPE_ORDER:
        subdir = kb_dir / TYPE_DIRS[entry_type]
        if not subdir.is_dir():
            continue
        for path in sorted(subdir.glob("*.md")):
            try:
                corpus.entries.append(parse_entry(path))
            except ParseError as exc:
                if strict:
                    raise
                corpus.parse_errors.append(exc)

    corpus.entries.sort(key=_sort_key)

    taxonomy_path = kb_dir / "taxonomy.yaml"
    if taxonomy_path.is_file():
        raw = load_yaml(taxonomy_path) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{taxonomy_path}: expected a mapping of term -> definition")
        for term, body in raw.items():
            try:
                corpus.taxonomy[str(term)] = TaxonomyTerm.model_validate(dict(body or {}))
            except Exception as exc:
                raise ValueError(f"{taxonomy_path}: term {term!r}: {exc}") from exc

    skills_path = kb_dir / "skills.yaml"
    if skills_path.is_file():
        raw = load_yaml(skills_path) or []
        if not isinstance(raw, list):
            raise ValueError(f"{skills_path}: expected a list of skill declarations")
        for row in raw:
            try:
                corpus.skills.append(SkillDeclaration.model_validate(dict(row)))
            except Exception as exc:
                raise ValueError(f"{skills_path}: {row!r}: {exc}") from exc

    identity_path = kb_dir / "identity.yaml"
    corpus.identity_path = identity_path if identity_path.is_file() else None

    return corpus
