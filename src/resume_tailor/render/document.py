"""The render document: what a template consumes.

Deliberately separate from both the knowledge base and the agents. Two
producers build one of these — `build_baseline` here, which renders the whole
corpus with no model involved, and the Writer's `draft.json` in M4 — and the
template knows about neither. Without that seam the template would end up
reading `Entry` objects directly and the Writer would have to fabricate them.

**Render-time visibility enforcement lives here** (spec-05 §7, RK-7). `nda` and
`private` content may be selected and shown to the user in review — it is their
own history — but it must not reach a file that leaves the machine. This is the
last gate, so it refuses rather than filters: silently dropping a bullet at
export is how you discover at an interview that your resume was shorter than
you thought.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..kb.identity import Identity
from ..kb.loader import Corpus
from ..kb.loader import Entry as KBEntry
from ..kb.schema import DateRange

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

EXPORTABLE_VISIBILITY = frozenset({"public"})

SectionKind = Literal["prose", "bullets", "entries"]


class VisibilityViolation(RuntimeError):
    """Non-public content reached the renderer. The render fails; nothing is written."""


def format_month(value: str | None) -> str | None:
    """`2026-02` -> `Feb 2026`; `present` -> `Present`."""
    if not value:
        return None
    if value == "present":
        return "Present"
    year, month = value.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def format_range(dates: DateRange | None) -> str | None:
    """`{start: 2025-08, end: 2026-02}` -> `Aug 2025 – Feb 2026`.

    The en dash is written as a literal here and translated to `--` by the
    escaper, so the document model stays readable and the LaTeX stays portable.
    """
    if dates is None:
        return None
    start = format_month(dates.start)
    end = format_month(dates.end)
    if end is None:
        return start
    if start == end:
        return start  # a one-month internship reads better as a single date
    return f"{start} – {end}"


@dataclass(frozen=True)
class Bullet:
    text: str
    #: Bold lead-in phrase, the pattern used throughout the source resume.
    lead: str | None = None
    #: Fact ids this bullet draws from. Never rendered; carried so the snapshot
    #: (R20) and the Validator can trace a claim back to its source.
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Entry:
    title: str
    org: str | None = None
    location: str | None = None
    dates: str | None = None
    #: Italic parenthetical after the title, as the Internships section uses.
    annotation: str | None = None
    bullets: tuple[Bullet, ...] = ()


@dataclass(frozen=True)
class Section:
    heading: str
    kind: SectionKind
    prose: str | None = None
    bullets: tuple[Bullet, ...] = ()
    entries: tuple[Entry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.prose or self.bullets or self.entries)


@dataclass(frozen=True)
class Contact:
    name: str
    headline: str | None = None
    location: str | None = None
    email: str | None = None
    phone: str | None = None
    links: tuple[tuple[str, str], ...] = ()

    def line_parts(self) -> list[str]:
        """The pipe-separated contact line, skipping anything unset."""
        parts = [p for p in (self.location, self.phone, self.email) if p]
        parts.extend(url for _, url in self.links)
        return parts


@dataclass(frozen=True)
class Document:
    contact: Contact
    contact_set: str
    sections: tuple[Section, ...] = ()
    #: Every fact id that contributed, for the audit trail.
    sources: frozenset[str] = field(default_factory=frozenset)

    @property
    def rendered_sections(self) -> list[Section]:
        return [s for s in self.sections if not s.is_empty]


def contact_for(identity: Identity, contact_set: str) -> Contact:
    details = identity.contact(contact_set)
    return Contact(
        name=identity.name,
        headline=identity.headline,
        location=identity.location,
        email=details.email,
        phone=details.phone,
        links=tuple(identity.links.pairs()),
    )


def assert_exportable(entries: list[KBEntry]) -> None:
    """Refuse to render non-public content (RK-7, spec-05 §7).

    Raises rather than filters. A renderer that quietly dropped `nda` bullets
    would produce a shorter resume than the user reviewed, and they would find
    out when an interviewer asked about a bullet that was never printed.
    """
    blocked = [
        (e.id, e.meta.visibility) for e in entries if e.meta.visibility not in EXPORTABLE_VISIBILITY
    ]
    if blocked:
        detail = ", ".join(f"{i} ({v})" for i, v in blocked)
        raise VisibilityViolation(
            f"refusing to render non-public content: {detail}. "
            "Mark it `visibility: public`, or exclude it from the selection."
        )


def _split_lead(text: str) -> tuple[str | None, str]:
    """Split `Bold lead-in: detail` into its two halves.

    The source resume uses this pattern in every bullet, and the knowledge base
    stores the bullet as one string. Splitting on the first colon reproduces the
    formatting without requiring every fact body to be restructured.

    Only splits on a colon in the first few words: a colon deep inside a
    sentence is punctuation, not a lead-in, and bolding half a sentence because
    of it would look like a bug.
    """
    head, sep, tail = text.partition(":")
    if sep and tail.strip() and len(head.split()) <= 8 and "\n" not in head:
        return head.strip(), tail.strip()
    return None, text.strip()


def _bullet_from_fact(entry: KBEntry) -> Bullet:
    """One knowledge-base fact as one resume bullet.

    The baseline render uses the fact's title as the lead-in and the first
    paragraph of its body as the detail. The Writer replaces both in M4; this
    exists so there is something faithful to compare against before any model
    is involved.
    """
    body = entry.body.split("<!--")[0].strip()
    paragraph = body.split("\n\n")[0].replace("\n", " ").strip()
    lead, text = _split_lead(paragraph)
    if lead is None:
        lead, text = entry.meta.title, paragraph
    return Bullet(text=text, lead=lead, sources=(entry.id,))


def build_baseline(
    corpus: Corpus,
    identity: Identity,
    contact_set: str,
    *,
    summary: str | None = None,
) -> Document:
    """Render the whole knowledge base, with no model involved.

    This is what proves AC-R7.1 — the existing resume rebuilt in LaTeX — and it
    is the fidelity reference the template is developed against. It is not what
    a tailored run produces: it includes everything, in knowledge-base order,
    with no selection and no rewriting.
    """
    public = [e for e in corpus.entries if e.meta.visibility in EXPORTABLE_VISIBILITY]
    assert_exportable(public)

    by_id = {e.id: e for e in public}
    sections: list[Section] = []
    used: set[str] = set()

    if summary:
        sections.append(Section(heading="Summary", kind="prose", prose=summary))

    skills = _skills_section(corpus, by_id)
    if skills:
        sections.append(skills)

    roles = [e for e in public if e.type == "role"]
    professional = [r for r in roles if getattr(r.meta, "employment", None) != "internship"]
    internships = [r for r in roles if getattr(r.meta, "employment", None) == "internship"]

    experience = _entries_section("Professional Experience", professional, by_id, used)
    if experience:
        sections.append(experience)

    if internships:
        sections.append(
            Section(
                heading="Internships",
                kind="bullets",
                # Reverse-chronological, like every other section. Corpus order
                # is alphabetical by id, which put a 2023 internship above a
                # 2024 one.
                bullets=tuple(_internship_bullet(r, by_id, used) for r in _sort_roles(internships)),
            )
        )

    credentials = _credentials_section(public, used)
    if credentials:
        sections.append(credentials)

    return Document(
        contact=contact_for(identity, contact_set),
        contact_set=contact_set,
        sections=tuple(sections),
        sources=frozenset(used),
    )


def _display_order(entry: KBEntry) -> tuple[int, str]:
    """Author-chosen order first, then id.

    Sorting by id alone looked deterministic and was arbitrary: it put the
    financial ledger above the trading engine purely because `l` precedes `t`.
    Deterministic is necessary but not sufficient — the order also has to be
    the one the author meant.
    """
    order = getattr(entry.meta, "order", None)
    return (order if order is not None else 1_000_000, entry.id)


def _sort_roles(roles: list[KBEntry]) -> list[KBEntry]:
    """Most recent first, which is how every reader scans a resume."""

    def key(role: KBEntry) -> str:
        dates = getattr(role.meta, "dates", None)
        if dates is None:
            return ""
        # `present` must sort above any date, so it becomes a sentinel.
        return "9999-99" if dates.end == "present" else (dates.end or dates.start)

    return sorted(roles, key=key, reverse=True)


def _entries_section(
    heading: str, roles: list[KBEntry], by_id: dict[str, KBEntry], used: set[str]
) -> Section | None:
    entries: list[Entry] = []
    for role in _sort_roles(roles):
        facts = [e for e in by_id.values() if e.type == "fact" and e.meta.parent == role.id]
        if not facts:
            continue
        used.add(role.id)
        bullets = []
        for fact in sorted(facts, key=_display_order):
            used.add(fact.id)
            bullets.append(_bullet_from_fact(fact))
        entries.append(
            Entry(
                title=role.meta.title,
                org=role.meta.org,
                location=getattr(role.meta, "location", None),
                dates=format_range(getattr(role.meta, "dates", None)),
                bullets=tuple(bullets),
            )
        )
    return Section(heading=heading, kind="entries", entries=tuple(entries)) if entries else None


def _internship_bullet(role: KBEntry, by_id: dict[str, KBEntry], used: set[str]) -> Bullet:
    """An internship renders as one bullet, as in the source resume."""
    used.add(role.id)
    facts = [e for e in by_id.values() if e.type == "fact" and e.meta.parent == role.id]
    details: list[str] = []
    sources = [role.id]
    for fact in sorted(facts, key=_display_order):
        used.add(fact.id)
        sources.append(fact.id)
        details.append(_bullet_from_fact(fact).text)

    dates = format_range(getattr(role.meta, "dates", None))
    org = role.meta.org
    lead = f"{role.meta.title} — {org}" if org else role.meta.title
    return Bullet(
        text=" ".join(details) or role.body.split("<!--")[0].strip(),
        lead=f"{lead} ({dates})" if dates else lead,
        sources=tuple(sources),
    )


def _skills_section(corpus: Corpus, by_id: dict[str, KBEntry]) -> Section | None:
    """Declared skills, grouped, with taxonomy labels rather than slugs.

    Only skills whose evidence is visible in this render are listed. A skill
    evidenced solely by an `nda` fact would otherwise appear with nothing
    behind it, which is the inflation rule 9 exists to prevent, reintroduced at
    render time.
    """
    groups: dict[str, list[str]] = {}
    for skill in corpus.skills:
        if not any(ev in by_id for ev in skill.evidence):
            continue
        term = corpus.taxonomy.get(skill.skill)
        label = term.label if term else skill.skill
        group = skill.group or (term.facet.title() if term else "Other")
        groups.setdefault(group, []).append(label)

    if not groups:
        return None

    bullets = tuple(Bullet(lead=group, text=", ".join(labels)) for group, labels in groups.items())
    return Section(heading="Technical Skills", kind="bullets", bullets=bullets)


def _credentials_section(public: list[KBEntry], used: set[str]) -> Section | None:
    bullets: list[Bullet] = []

    for entry in [e for e in public if e.type == "education"]:
        used.add(entry.id)
        metrics = ", ".join(f"{m.what}: {m.value}" for m in entry.meta.metrics)
        tail = f"{entry.meta.org}" if entry.meta.org else ""
        if metrics:
            tail = f"{tail} | {metrics}" if tail else metrics
        bullets.append(Bullet(lead=entry.meta.title, text=tail, sources=(entry.id,)))

    credentials = [e for e in public if e.type in ("certification", "award")]
    if credentials:
        for entry in credentials:
            used.add(entry.id)
        names = " | ".join(e.meta.title for e in credentials)
        bullets.append(
            Bullet(
                lead="Awards & Certifications",
                text=names,
                sources=tuple(e.id for e in credentials),
            )
        )

    if not bullets:
        return None
    return Section(heading="Education & Certifications", kind="bullets", bullets=tuple(bullets))
