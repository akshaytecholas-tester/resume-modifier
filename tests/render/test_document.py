"""The render document: what the template consumes (spec-05 §7, RK-7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.identity import Identity, normalise_identity
from resume_tailor.kb.loader import load_corpus
from resume_tailor.kb.schema import DateRange
from resume_tailor.render.document import (
    VisibilityViolation,
    _split_lead,
    build_baseline,
    format_month,
    format_range,
)

from ..conftest import write_entry


@pytest.fixture
def identity() -> Identity:
    return Identity.model_validate(
        normalise_identity({"name": "Ada Lovelace", "email": "ada@example.com"})
    )


# -- dates -----------------------------------------------------------------


def test_month_formatting() -> None:
    assert format_month("2026-02") == "Feb 2026"
    assert format_month("present") == "Present"
    assert format_month(None) is None


def test_range_formatting() -> None:
    assert format_range(DateRange(start="2025-08", end="2026-02")) == "Aug 2025 – Feb 2026"
    assert format_range(DateRange(start="2026-02", end="present")) == "Feb 2026 – Present"
    assert format_range(None) is None


def test_single_month_range_is_not_repeated() -> None:
    """A one-month internship reads as `Jun 2024`, not `Jun 2024 – Jun 2024`."""
    assert format_range(DateRange(start="2024-06", end="2024-06")) == "Jun 2024"


# -- lead-in splitting -----------------------------------------------------


def test_lead_is_split_on_a_short_leading_colon() -> None:
    assert _split_lead("Real-Time Engine: built it") == ("Real-Time Engine", "built it")


def test_colon_deep_in_a_sentence_is_not_a_lead() -> None:
    """Bolding half a sentence because it contains a colon looks like a bug."""
    text = "We considered many options over several months and chose this: Postgres"
    assert _split_lead(text) == (None, text)


def test_no_colon_yields_no_lead() -> None:
    assert _split_lead("Just a sentence") == (None, "Just a sentence")


# -- visibility is enforced at render --------------------------------------


def test_nda_content_is_refused_not_filtered(kb: Path, identity: Identity) -> None:
    """RK-7. Refusing beats filtering: a silently shorter resume is one the
    user reviewed but never sent."""
    write_entry(
        kb,
        "facts",
        "acme-secret",
        """
        id: acme-secret
        type: fact
        parent: acme-engineer
        title: Client work
        tags: [python]
        depth: working
        verifiable: true
        visibility: nda
    """,
    )
    corpus = load_corpus(kb)
    doc = build_baseline(corpus, identity, "default")
    assert "acme-secret" not in doc.sources

    from resume_tailor.render.document import assert_exportable

    with pytest.raises(VisibilityViolation, match="acme-secret"):
        assert_exportable(corpus.entries)


def test_private_is_refused_too(kb: Path) -> None:
    from resume_tailor.render.document import assert_exportable

    write_entry(
        kb,
        "facts",
        "acme-private",
        """
        id: acme-private
        type: fact
        parent: acme-engineer
        title: Private
        tags: [python]
        depth: working
        verifiable: true
        visibility: private
    """,
    )
    with pytest.raises(VisibilityViolation, match="private"):
        assert_exportable(load_corpus(kb).entries)


# -- ordering --------------------------------------------------------------


def test_explicit_order_beats_alphabetical(kb: Path, identity: Identity) -> None:
    """Sorting by id is deterministic and arbitrary; it put the ledger above
    the trading engine because `l` precedes `t`."""
    for stem, order in (("acme-zulu", 1), ("acme-alpha", 2)):
        write_entry(
            kb,
            "facts",
            stem,
            f"""
            id: {stem}
            type: fact
            parent: acme-engineer
            title: {stem}
            tags: [python]
            depth: working
            verifiable: true
            visibility: public
            order: {order}
        """,
        )
    doc = build_baseline(load_corpus(kb), identity, "default")
    experience = next(s for s in doc.sections if s.heading == "Professional Experience")
    leads = [b.lead for b in experience.entries[0].bullets]
    assert leads[:2] == ["acme-zulu", "acme-alpha"]


def test_unordered_entries_sort_last_and_stay_deterministic(kb: Path, identity: Identity) -> None:
    write_entry(
        kb,
        "facts",
        "acme-ordered",
        """
        id: acme-ordered
        type: fact
        parent: acme-engineer
        title: Ordered
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
        order: 1
    """,
    )
    doc = build_baseline(load_corpus(kb), identity, "default")
    experience = next(s for s in doc.sections if s.heading == "Professional Experience")
    assert experience.entries[0].bullets[0].lead == "Ordered"


# -- sections --------------------------------------------------------------


def test_summary_is_included_only_when_supplied(kb: Path, identity: Identity) -> None:
    """The summary is Writer output, tailored per posting, so the baseline has
    none unless one is handed to it."""
    corpus = load_corpus(kb)
    assert not any(
        s.heading == "Summary" for s in build_baseline(corpus, identity, "default").sections
    )
    doc = build_baseline(corpus, identity, "default", summary="Prose.")
    assert doc.sections[0].heading == "Summary"


def test_roles_without_facts_are_dropped(kb: Path, identity: Identity) -> None:
    """A role with nothing under it would render as a bare heading."""
    write_entry(
        kb,
        "roles",
        "acme-empty",
        """
        id: acme-empty
        type: role
        title: Empty
        org: Acme
        dates: {start: 2020-01, end: 2020-06}
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    doc = build_baseline(load_corpus(kb), identity, "default")
    experience = next(s for s in doc.sections if s.heading == "Professional Experience")
    assert "acme-empty" not in {e.title for e in experience.entries}


def test_skills_with_no_visible_evidence_are_dropped(kb: Path, identity: Identity) -> None:
    """Rule 9's inflation guard, re-applied at render.

    A skill evidenced only by an `nda` fact would otherwise be listed with
    nothing behind it in the exported document.
    """
    write_entry(
        kb,
        "facts",
        "acme-hidden",
        """
        id: acme-hidden
        type: fact
        parent: acme-engineer
        title: Hidden
        tags: [python]
        depth: working
        verifiable: true
        visibility: nda
    """,
    )
    (kb / "skills.yaml").write_text(
        "- skill: go\n  depth: working\n  evidence: [acme-hidden]\n", encoding="utf-8"
    )
    doc = build_baseline(load_corpus(kb), identity, "default")
    assert not any(s.heading == "Technical Skills" for s in doc.sections)


def test_sources_records_every_contributing_entry(kb: Path, identity: Identity) -> None:
    doc = build_baseline(load_corpus(kb), identity, "default")
    assert {"acme-engineer", "acme-pipeline"} <= doc.sources


def test_contact_set_selects_the_right_details() -> None:
    identity = Identity.model_validate(
        normalise_identity(
            {
                "name": "Ada",
                "contacts": {
                    "referral": {"email": "r@example.com"},
                    "direct": {"email": "d@example.com"},
                },
                "default_set": "direct",
            }
        )
    )
    from resume_tailor.render.document import contact_for

    assert contact_for(identity, "referral").email == "r@example.com"
    assert contact_for(identity, "direct").email == "d@example.com"
