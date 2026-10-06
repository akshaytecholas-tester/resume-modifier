"""The ten validation rules (spec-01 §4).

Enforced on every write, before any byte reaches disk, so the knowledge base is
never in a state the loader cannot read.

Errors block a write; warnings do not. The split is not cosmetic: rule 5
(unknown tag) is deliberately a **warning**, because tags describe and do not
gate (P5), and refusing a write over vocabulary bookkeeping would push the user
toward editing files outside the validated path. Rule 4 (dangling parent) is an
**error**, because a fact with no resolvable parent has nowhere to render.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .identity import Identity, load_identity
from .loader import Corpus
from .schema import ID_RE, PARENT_TYPES

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    """One validation finding, shaped so the UI can render it per field."""

    level: Level
    code: str
    message: str
    entry_id: str | None = None
    field: str | None = None
    path: Path | None = None

    def __str__(self) -> str:
        where = self.entry_id or (str(self.path) if self.path else "kb")
        field = f".{self.field}" if self.field else ""
        return f"[{self.level}] {where}{field}: {self.message} ({self.code})"


@dataclass
class Report:
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok


def validate_corpus(corpus: Corpus, *, identity: Identity | None = None) -> Report:
    issues: list[Issue] = []

    # Anything that failed to parse is reported first; it has no metadata to
    # check further, and a cascade of follow-on errors would bury the cause.
    for exc in corpus.parse_errors:
        issues.append(Issue("error", "parse", exc.message, path=exc.path))

    entries = corpus.entries
    by_id: dict[str, list] = {}
    for entry in entries:
        by_id.setdefault(entry.id, []).append(entry)

    # Rule 1 — id is a slug and equals the filename stem.
    for entry in entries:
        if not ID_RE.match(entry.id):
            issues.append(
                Issue(
                    "error",
                    "id-format",
                    f"id {entry.id!r} is not a slug",
                    entry.id,
                    "id",
                    entry.path,
                )
            )
        if entry.path.stem != entry.id:
            issues.append(
                Issue(
                    "error",
                    "id-filename-mismatch",
                    f"id {entry.id!r} does not match filename stem {entry.path.stem!r}; "
                    "rename the file or correct the id",
                    entry.id,
                    "id",
                    entry.path,
                )
            )

    # Rule 2 — id unique across the whole KB, not merely within a directory.
    for entry_id, group in sorted(by_id.items()):
        if len(group) > 1:
            where = ", ".join(str(e.path) for e in group)
            issues.append(
                Issue(
                    "error",
                    "id-duplicate",
                    f"id {entry_id!r} used by {len(group)} files: {where}",
                    entry_id,
                    "id",
                )
            )

    # Rules 3, 7, 8, 10 are enforced by the pydantic models in schema.py and
    # surface as parse errors above. Checking them twice would let the two
    # copies drift.

    resolvable = {entry_id for entry_id in by_id}
    parent_types = {e.id: e.type for e in entries}

    # Rule 4 — parent resolves to an existing role or project.
    for entry in entries:
        parent = getattr(entry.meta, "parent", None)
        if parent is None:
            continue
        if parent not in resolvable:
            issues.append(
                Issue(
                    "error",
                    "parent-missing",
                    f"parent {parent!r} does not exist",
                    entry.id,
                    "parent",
                    entry.path,
                )
            )
        elif parent_types[parent] not in PARENT_TYPES:
            issues.append(
                Issue(
                    "error",
                    "parent-wrong-type",
                    f"parent {parent!r} is a {parent_types[parent]}; "
                    f"must be one of: {', '.join(sorted(PARENT_TYPES))}",
                    entry.id,
                    "parent",
                    entry.path,
                )
            )

    # Rule 5 — tags exist in the taxonomy. A warning, never a silent orphan.
    taxonomy = corpus.taxonomy
    for entry in entries:
        for tag in entry.meta.tags:
            if tag not in taxonomy:
                issues.append(
                    Issue(
                        "warning",
                        "tag-unknown",
                        f"tag {tag!r} is not in taxonomy.yaml — add it to the vocabulary "
                        "or correct the tag",
                        entry.id,
                        "tags",
                        entry.path,
                    )
                )

    # Rule 6 — related ids resolve.
    for entry in entries:
        for related in entry.meta.related:
            if related == entry.id:
                issues.append(
                    Issue(
                        "warning",
                        "related-self",
                        "entry lists itself in `related`",
                        entry.id,
                        "related",
                        entry.path,
                    )
                )
            elif related not in resolvable:
                issues.append(
                    Issue(
                        "error",
                        "related-missing",
                        f"related id {related!r} does not exist",
                        entry.id,
                        "related",
                        entry.path,
                    )
                )

    # Rule 9 — every declared skill cites evidence that exists. A skill with no
    # resolvable evidence is precisely where resume inflation lives.
    seen_skills: set[str] = set()
    for skill in corpus.skills:
        if skill.skill in seen_skills:
            issues.append(
                Issue(
                    "error",
                    "skill-duplicate",
                    f"skill {skill.skill!r} declared twice",
                    skill.skill,
                    "skill",
                )
            )
        seen_skills.add(skill.skill)

        if skill.skill not in taxonomy:
            issues.append(
                Issue(
                    "warning",
                    "skill-untaxonomised",
                    f"skill {skill.skill!r} is not in taxonomy.yaml",
                    skill.skill,
                    "skill",
                )
            )
        for evidence_id in skill.evidence:
            if evidence_id not in resolvable:
                issues.append(
                    Issue(
                        "error",
                        "skill-evidence-missing",
                        f"evidence id {evidence_id!r} does not exist",
                        skill.skill,
                        "evidence",
                    )
                )

    # Taxonomy internal consistency. A warning: a dangling `parent` is cosmetic
    # and must not block an unrelated write.
    for term, definition in taxonomy.items():
        if definition.parent and definition.parent not in taxonomy:
            issues.append(
                Issue(
                    "warning",
                    "taxonomy-parent-missing",
                    f"taxonomy term {term!r} has parent {definition.parent!r}, which is undefined",
                    term,
                    "parent",
                )
            )

    # Orphaned roles are worth saying out loud: a role with no facts renders as
    # a heading with nothing under it.
    for role in corpus.of_type("role"):
        if not corpus.facts_of(role.id):
            issues.append(
                Issue(
                    "warning",
                    "role-no-facts",
                    "role has no facts; it would render as an empty heading",
                    role.id,
                    None,
                    role.path,
                )
            )

    if identity is not None:
        issues.extend(_identity_issues(identity))

    return Report(issues)


def _identity_issues(identity: Identity) -> list[Issue]:
    issues: list[Issue] = []
    for set_name, contact in identity.contacts.items():
        if contact.email and "@" not in contact.email:
            issues.append(
                Issue(
                    "warning",
                    "contact-email-shape",
                    f"contact set {set_name!r} email {contact.email!r} has no '@'",
                    "identity",
                    f"contacts.{set_name}.email",
                )
            )
    return issues


def validate_kb(kb_dir: Path, corpus: Corpus) -> Report:
    """Validate a corpus plus `identity.yaml` when it is present.

    `identity.yaml` is gitignored and may legitimately be absent on a fresh
    clone, so its absence is a warning telling the user what to copy, not an
    error that stops them looking at the rest of the knowledge base.
    """
    identity: Identity | None = None
    extra: list[Issue] = []

    path = kb_dir / "identity.yaml"
    if path.is_file():
        try:
            identity = load_identity(path)
        except Exception as exc:
            extra.append(Issue("error", "identity-invalid", str(exc), "identity", None, path))
    else:
        extra.append(
            Issue(
                "warning",
                "identity-missing",
                "kb/identity.yaml not found — copy kb/identity.example.yaml to it and fill "
                "it in (it is gitignored by design)",
                "identity",
                None,
                path,
            )
        )

    report = validate_corpus(corpus, identity=identity)
    report.issues.extend(extra)
    return report
