"""Turning a Writer draft into a renderable document, and applying cuts."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.identity import Identity, normalise_identity
from resume_tailor.kb.loader import load_corpus
from resume_tailor.render.document import (
    VisibilityViolation,
    apply_validation,
    document_from_draft,
)

from ..conftest import write_entry

DRAFT = {
    "summary": "Backend engineer.",
    "summary_sources": ["acme-pipeline"],
    "sections": [
        {
            "kind": "experience",
            "role_id": "acme-engineer",
            "bullets": [
                {"lead": "Good", "text": "Supported claim.", "sources": ["acme-pipeline"]},
                {"lead": "Bad", "text": "Led a team of five.", "sources": ["acme-pipeline"]},
            ],
        }
    ],
    "skills": [{"group": "Languages", "items": ["Python"], "sources": ["acme-pipeline"]}],
}


@pytest.fixture
def identity() -> Identity:
    return Identity.model_validate(normalise_identity({"name": "Ada", "email": "ada@example.com"}))


# -- applying the Validator ------------------------------------------------


def test_a_cut_removes_the_bullet() -> None:
    validation = {
        "cuts": [{"bullet": "Led a team of five.", "reason": "no source supports it"}],
        "warnings": [],
    }
    result, notes = apply_validation(DRAFT, validation)
    texts = [b["text"] for b in result["sections"][0]["bullets"]]
    assert texts == ["Supported claim."]
    assert "no source supports it" in notes[0]


def test_a_replacement_rewrites_rather_than_removes() -> None:
    validation = {
        "cuts": [
            {
                "bullet": "Led a team of five.",
                "replacement": "Drove the work.",
                "reason": "team size unsupported",
            }
        ]
    }
    result, notes = apply_validation(DRAFT, validation)
    texts = [b["text"] for b in result["sections"][0]["bullets"]]
    assert texts == ["Supported claim.", "Drove the work."]
    assert notes[0].startswith("corrected")


def test_warnings_are_not_applied() -> None:
    """A warning means "show the user this bullet with a mark against it".
    Applying it here would hide the thing they most need to see — NDA content
    above all, which the renderer refuses separately."""
    validation = {
        "cuts": [],
        "warnings": [{"bullet": "Led a team of five.", "kind": "nda", "reason": "client name"}],
    }
    result, notes = apply_validation(DRAFT, validation)
    assert len(result["sections"][0]["bullets"]) == 2
    assert notes == []


def test_the_original_draft_is_not_mutated() -> None:
    """The artifact on disk stays as the Writer produced it, so the two are
    comparable afterwards."""
    before = len(DRAFT["sections"][0]["bullets"])
    apply_validation(DRAFT, {"cuts": [{"bullet": "Led a team of five.", "reason": "x"}]})
    assert len(DRAFT["sections"][0]["bullets"]) == before


def test_a_clean_validation_changes_nothing() -> None:
    result, notes = apply_validation(DRAFT, {"verdict": "clean", "cuts": [], "clean": True})
    assert result is DRAFT and notes == []


# -- building the document -------------------------------------------------


def test_role_metadata_comes_from_the_kb_not_the_draft(kb: Path, identity: Identity) -> None:
    """Dates and organisations are facts. A model restating them is a chance
    for them to drift, so the draft supplies only the prose it wrote."""
    doc = document_from_draft(DRAFT, load_corpus(kb), identity, "default")
    experience = next(s for s in doc.sections if s.heading == "Professional Experience")
    entry = experience.entries[0]
    assert entry.title == "Software Engineer"  # from kb/roles/acme-engineer.md
    assert entry.org == "Acme"
    assert entry.dates == "Jan 2024 – Present"


def test_sources_are_carried_for_the_audit_trail(kb: Path, identity: Identity) -> None:
    doc = document_from_draft(DRAFT, load_corpus(kb), identity, "default")
    assert "acme-pipeline" in doc.sources
    assert "acme-engineer" in doc.sources


def test_sections_are_ordered_as_the_resume_is(kb: Path, identity: Identity) -> None:
    doc = document_from_draft(DRAFT, load_corpus(kb), identity, "default")
    assert [s.heading for s in doc.rendered_sections] == [
        "Summary",
        "Technical Skills",
        "Professional Experience",
    ]


def test_empty_bullets_are_dropped(kb: Path, identity: Identity) -> None:
    draft = {
        "sections": [
            {
                "kind": "experience",
                "role_id": "acme-engineer",
                "bullets": [{"text": "   ", "sources": []}],
            }
        ]
    }
    doc = document_from_draft(draft, load_corpus(kb), identity, "default")
    assert not any(s.heading == "Professional Experience" for s in doc.rendered_sections)


def test_an_unknown_role_id_keeps_the_bullets(kb: Path, identity: Identity) -> None:
    """Losing content over a bad reference is the silent omission this exists
    to prevent. The Validator's id check reports it instead."""
    draft = {
        "sections": [
            {
                "kind": "experience",
                "role_id": "ghost-role",
                "bullets": [{"text": "Real work.", "sources": ["acme-pipeline"]}],
            }
        ]
    }
    doc = document_from_draft(draft, load_corpus(kb), identity, "default")
    experience = next(s for s in doc.sections if s.heading == "Professional Experience")
    assert experience.entries[0].bullets[0].text == "Real work."


def test_nda_sources_refuse_the_render(kb: Path, identity: Identity) -> None:
    """RK-7, at the last gate before content leaves the machine."""
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
    draft = {
        "sections": [
            {
                "kind": "experience",
                "role_id": "acme-engineer",
                "bullets": [{"text": "Secret.", "sources": ["acme-secret"]}],
            }
        ]
    }
    with pytest.raises(VisibilityViolation, match="acme-secret"):
        document_from_draft(draft, load_corpus(kb), identity, "default")


# -- regressions found by running the real pipeline ------------------------

SUMMARY_DRAFT = {
    "summary": "Comfortable owning fintech services and improving small-team velocity.",
    "summary_sources": ["acme-pipeline"],
    "sections": [
        {
            "kind": "experience",
            "role_id": "acme-engineer",
            "bullets": [{"text": "Supported claim.", "sources": ["acme-pipeline"]}],
        }
    ],
}


def test_a_cut_summary_is_actually_applied() -> None:
    """Found by running the pipeline for real, not by a test.

    The Validator cuts the summary by quoting it in the same `bullet` field it
    uses for bullets. An earlier version walked only the bullet lists, so the
    cut was silently ignored and the unsupported claim reached the PDF — the
    exact Q1 failure the Validator exists to catch.
    """
    validation = {
        "cuts": [
            {
                "section": "summary",
                "bullet": SUMMARY_DRAFT["summary"],
                "replacement": "Backend engineer with production Python experience.",
                "reason": "'small-team velocity' smuggles a team size no fact supports",
            }
        ]
    }
    result, notes = apply_validation(SUMMARY_DRAFT, validation)
    assert result["summary"] == "Backend engineer with production Python experience."
    assert any("summary" in n for n in notes)


def test_a_summary_cut_with_no_replacement_empties_it() -> None:
    validation = {"cuts": [{"bullet": SUMMARY_DRAFT["summary"], "reason": "unsupported"}]}
    result, _ = apply_validation(SUMMARY_DRAFT, validation)
    assert result["summary"] == ""


def test_a_cut_that_matches_nothing_is_reported_loudly() -> None:
    """Silence here would mean the Validator objected, nothing changed, and
    nobody was told — so the claim ships with a clean-looking run."""
    validation = {"cuts": [{"bullet": "text that is not in the draft", "reason": "bad claim"}]}
    _, notes = apply_validation(SUMMARY_DRAFT, validation)
    assert any("UNAPPLIED" in n for n in notes)
    assert any("bad claim" in n for n in notes)


def test_education_renders_as_bullets_not_a_duplicated_heading(
    kb: Path, identity: Identity
) -> None:
    """Also found by running it: as an entry, the degree printed twice — once
    as the entry heading and again in its own bullet, because the Writer puts
    the whole credential in the bullet text."""
    draft = {
        "sections": [
            {
                "kind": "education",
                "role_id": "acme-engineer",
                "bullets": [
                    {
                        "lead": "B.Tech, Information Technology — Example University",
                        "text": "CGPA 9.13 / 10.",
                        "sources": ["acme-pipeline"],
                    }
                ],
            }
        ]
    }
    doc = document_from_draft(draft, load_corpus(kb), identity, "default")
    section = next(s for s in doc.rendered_sections if s.heading == "Education & Certifications")
    assert section.kind == "bullets"
    assert section.entries == ()
    assert len(section.bullets) == 1
