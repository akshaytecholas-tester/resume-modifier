"""The ten rules of spec-01 §4, each with a passing and a failing case.

Every rule here exists because its absence is silent: a dangling parent renders
nothing, a duplicate id makes one entry invisible, an unevidenced skill is
inflation. A test that only proves the happy path would not catch any of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.loader import load_corpus
from resume_tailor.kb.validate import validate_corpus

from .conftest import write_entry


def codes(kb: Path, level: str | None = None) -> set[str]:
    report = validate_corpus(load_corpus(kb))
    issues = report.issues if level is None else [i for i in report.issues if i.level == level]
    return {i.code for i in issues}


def test_baseline_is_clean(kb: Path) -> None:
    report = validate_corpus(load_corpus(kb))
    assert report.ok, [str(i) for i in report.issues]
    assert not report.warnings, [str(i) for i in report.warnings]


# -- rule 1: id is a slug and equals the filename stem ----------------------


def test_id_filename_mismatch_is_an_error(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "wrong-name",
        """
        id: acme-other
        type: fact
        parent: acme-engineer
        title: Other
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "id-filename-mismatch" in codes(kb, "error")


def test_non_slug_id_fails_at_parse(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "Bad_Id",
        """
        id: Bad_Id
        type: fact
        parent: acme-engineer
        title: Bad
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    # pydantic's pattern constraint rejects it, so it never becomes an entry.
    assert "parse" in codes(kb, "error")


# -- rule 2: id unique across the whole KB, not per directory ---------------


def test_duplicate_id_across_directories(kb: Path) -> None:
    write_entry(
        kb,
        "projects",
        "acme-pipeline",
        """
        id: acme-pipeline
        type: project
        title: Clashing project
        dates: {start: 2024-01}
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "id-duplicate" in codes(kb, "error")


# -- rule 3: required fields present ---------------------------------------


def test_missing_required_field(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-nodepth",
        """
        id: acme-nodepth
        type: fact
        parent: acme-engineer
        title: No depth
        tags: [python]
        verifiable: true
        visibility: public
    """,
    )
    assert "parse" in codes(kb, "error")


def test_unknown_field_is_rejected(kb: Path) -> None:
    """A typo'd field name must fail loudly.

    Accepting it would mean a misspelled `visibilty` leaves the entry at the
    `public` default while looking configured — a guard that silently is not one.
    """
    write_entry(
        kb,
        "facts",
        "acme-typo",
        """
        id: acme-typo
        type: fact
        parent: acme-engineer
        title: Typo
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
        visibilty: nda
    """,
    )
    assert "parse" in codes(kb, "error")


# -- rule 4: parent resolves to a role or project --------------------------


def test_dangling_parent(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-orphan",
        """
        id: acme-orphan
        type: fact
        parent: does-not-exist
        title: Orphan
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "parent-missing" in codes(kb, "error")


def test_parent_of_the_wrong_type(kb: Path) -> None:
    write_entry(
        kb,
        "awards",
        "acme-award",
        """
        id: acme-award
        type: award
        title: An award
        org: Acme
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    write_entry(
        kb,
        "facts",
        "acme-under-award",
        """
        id: acme-under-award
        type: fact
        parent: acme-award
        title: Parented to an award
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "parent-wrong-type" in codes(kb, "error")


# -- rule 5: unknown tags WARN, they do not block --------------------------


def test_unknown_tag_warns_and_does_not_block(kb: Path) -> None:
    """Tags describe, they do not gate (spec-01 P5).

    Blocking a write over vocabulary bookkeeping would push the user to edit
    files outside the validated path, which costs more than the orphan tag.
    """
    write_entry(
        kb,
        "facts",
        "acme-newtag",
        """
        id: acme-newtag
        type: fact
        parent: acme-engineer
        title: New tag
        tags: [python, kubernetes]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    report = validate_corpus(load_corpus(kb))
    assert "tag-unknown" in {i.code for i in report.warnings}
    assert report.ok


def test_duplicate_tags_rejected(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-dupetag",
        """
        id: acme-dupetag
        type: fact
        parent: acme-engineer
        title: Duplicate tags
        tags: [python, python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "parse" in codes(kb, "error")


# -- rule 6: related ids resolve -------------------------------------------


def test_dangling_related(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-rel",
        """
        id: acme-rel
        type: fact
        parent: acme-engineer
        title: Bad related
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
        related: [nope]
    """,
    )
    assert "related-missing" in codes(kb, "error")


def test_self_reference_warns(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-self",
        """
        id: acme-self
        type: fact
        parent: acme-engineer
        title: Self related
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
        related: [acme-self]
    """,
    )
    report = validate_corpus(load_corpus(kb))
    assert "related-self" in {i.code for i in report.warnings}
    assert report.ok


# -- rule 7: enum values ---------------------------------------------------


def test_bad_depth_and_visibility(kb: Path) -> None:
    for stem, field, value in (
        ("acme-baddepth", "depth", "guru"),
        ("acme-badvis", "visibility", "secret"),
    ):
        fields = {"depth": "working", "visibility": "public"}
        fields[field] = value
        write_entry(
            kb,
            "facts",
            stem,
            f"""
            id: {stem}
            type: fact
            parent: acme-engineer
            title: Bad enum
            tags: [python]
            depth: {fields["depth"]}
            verifiable: true
            visibility: {fields["visibility"]}
        """,
        )
    assert "parse" in codes(kb, "error")


# -- rule 8: dates -------------------------------------------------------


def test_bad_date_format_and_reversed_range(kb: Path) -> None:
    write_entry(
        kb,
        "roles",
        "acme-baddate",
        """
        id: acme-baddate
        type: role
        title: Bad date
        org: Acme
        dates: {start: 2024, end: present}
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    write_entry(
        kb,
        "roles",
        "acme-reversed",
        """
        id: acme-reversed
        type: role
        title: Reversed
        org: Acme
        dates: {start: 2025-06, end: 2024-01}
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "parse" in codes(kb, "error")
    assert len([i for i in validate_corpus(load_corpus(kb)).errors if i.code == "parse"]) == 2


def test_present_end_date_is_accepted(kb: Path) -> None:
    assert validate_corpus(load_corpus(kb)).ok


# -- rule 9: skills cite evidence that resolves ---------------------------


def test_skill_with_dangling_evidence(kb: Path) -> None:
    (kb / "skills.yaml").write_text(
        "- skill: python\n  depth: working\n  evidence: [ghost-fact]\n", encoding="utf-8"
    )
    assert "skill-evidence-missing" in codes(kb, "error")


def test_skill_with_no_evidence_at_all_is_rejected(kb: Path) -> None:
    """An empty `evidence` list is where resume inflation lives (spec-01 §3.5)."""
    (kb / "skills.yaml").write_text(
        "- skill: python\n  depth: expert\n  evidence: []\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="evidence"):
        load_corpus(kb)


def test_valid_skill_passes(kb: Path) -> None:
    (kb / "skills.yaml").write_text(
        "- skill: rag\n  depth: working\n  evidence: [acme-pipeline]\n", encoding="utf-8"
    )
    assert validate_corpus(load_corpus(kb)).ok


def test_duplicate_skill_declaration(kb: Path) -> None:
    (kb / "skills.yaml").write_text(
        "- skill: python\n  depth: working\n  evidence: [acme-pipeline]\n"
        "- skill: python\n  depth: expert\n  evidence: [acme-pipeline]\n",
        encoding="utf-8",
    )
    assert "skill-duplicate" in codes(kb, "error")


# -- rule 10: metrics are non-empty ---------------------------------------


def test_empty_metric_value_rejected(kb: Path) -> None:
    write_entry(
        kb,
        "facts",
        "acme-emptymetric",
        """
        id: acme-emptymetric
        type: fact
        parent: acme-engineer
        title: Empty metric
        tags: [python]
        metrics:
          - {value: "", what: "nothing"}
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    assert "parse" in codes(kb, "error")


# -- beyond the ten: things worth saying out loud -------------------------


def test_role_without_facts_warns(kb: Path) -> None:
    """A role with no facts renders as a heading with nothing under it."""
    write_entry(
        kb,
        "roles",
        "acme-empty",
        """
        id: acme-empty
        type: role
        title: Empty role
        org: Acme
        dates: {start: 2023-01, end: 2023-06}
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    report = validate_corpus(load_corpus(kb))
    assert "role-no-facts" in {i.code for i in report.warnings}
    assert report.ok


def test_every_rule_reports_all_problems_in_one_pass(kb: Path) -> None:
    """Validation must not stop at the first failure.

    `rt kb validate` is run to find out what is wrong with the knowledge base;
    returning one error per invocation would make fixing twelve of them twelve
    round trips.
    """
    write_entry(
        kb,
        "facts",
        "acme-a",
        """
        id: acme-a
        type: fact
        parent: missing-one
        title: A
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    write_entry(
        kb,
        "facts",
        "acme-b",
        """
        id: acme-b
        type: fact
        parent: missing-two
        title: B
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
    )
    errors = validate_corpus(load_corpus(kb)).errors
    assert len([e for e in errors if e.code == "parent-missing"]) == 2
