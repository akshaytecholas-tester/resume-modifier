"""The seven-step write path (spec-04 §2).

Each step exists because its absence is a specific, silent failure. These tests
name the failure rather than the step.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from resume_tailor.kb.write import (
    Conflict,
    StillReferenced,
    ValidationFailed,
    WriteError,
    content_hash,
    delete_entry,
    read_entry,
    write_entry,
)

FACT = {
    "id": "acme-new",
    "type": "fact",
    "parent": "acme-engineer",
    "title": "A new fact",
    "tags": ["python"],
    "depth": "working",
    "verifiable": True,
    "visibility": "public",
}


def kb_of(project: Path) -> Path:
    return project / "kb"


def test_a_valid_entry_is_written_and_committed(project: Path) -> None:
    result = write_entry(kb_of(project), "fact", "acme-new", FACT, "The body.")
    assert result.path.is_file()
    assert result.commit, "a write must leave history (AC-R8.3)"
    assert "The body." in result.path.read_text()


def test_the_commit_lands_in_the_kb_repo_not_a_parent(project: Path) -> None:
    """OQ-9. Committing to the parent repository would publish the career
    record to a public remote on the next push."""
    write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.")
    log = subprocess.run(
        ["git", "-C", str(kb_of(project)), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "kb: create acme-new" in log


def test_an_unchanged_save_makes_no_empty_commit(project: Path) -> None:
    """History that fills with no-op commits stops being worth reading."""
    first = write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.")
    again = write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.", base_hash=first.hash)
    assert again.commit is None


# -- step 1: validate ------------------------------------------------------


def test_an_invalid_entry_never_reaches_disk(project: Path) -> None:
    """The knowledge base must never be in a state the loader cannot read."""
    bad = {**FACT, "depth": "guru"}
    with pytest.raises(ValidationFailed):
        write_entry(kb_of(project), "fact", "acme-new", bad, "Body.")
    assert not (kb_of(project) / "facts" / "acme-new.md").exists()


def test_a_dangling_parent_is_refused(project: Path) -> None:
    with pytest.raises(ValidationFailed) as exc:
        write_entry(kb_of(project), "fact", "acme-new", {**FACT, "parent": "ghost"}, "Body.")
    assert any("parent" in str(d) for d in exc.value.detail)


def test_errors_are_per_field_for_the_ui(project: Path) -> None:
    with pytest.raises(ValidationFailed) as exc:
        write_entry(kb_of(project), "fact", "acme-new", {**FACT, "parent": "ghost"}, "B.")
    assert exc.value.detail[0]["field"] == "parent"
    assert exc.value.remedy


def test_a_mismatched_id_is_refused(project: Path) -> None:
    with pytest.raises(ValidationFailed, match="id"):
        write_entry(kb_of(project), "fact", "acme-new", {**FACT, "id": "other"}, "B.")


# -- step 2: path containment ---------------------------------------------


@pytest.mark.parametrize(
    "hostile", ["../../../etc/passwd", "..", "a/b", "/etc/passwd", "A-B", "a b"]
)
def test_a_hostile_id_cannot_escape_kb(project: Path, hostile: str) -> None:
    """The id becomes a path. Without this check it is an arbitrary-write
    primitive on the user's own machine."""
    with pytest.raises(WriteError):
        write_entry(kb_of(project), "fact", hostile, FACT, "Body.")


# -- step 3: base_hash -----------------------------------------------------


def test_overwriting_without_a_base_hash_is_refused(project: Path) -> None:
    write_entry(kb_of(project), "fact", "acme-new", FACT, "First.")
    with pytest.raises(Conflict):
        write_entry(kb_of(project), "fact", "acme-new", FACT, "Second.")


def test_a_stale_base_hash_is_refused(project: Path) -> None:
    """There really are three writers — browser, text editor, agents. Without
    this a UI save silently destroys a vim edit from two minutes earlier."""
    write_entry(kb_of(project), "fact", "acme-new", FACT, "First.")
    path = kb_of(project) / "facts" / "acme-new.md"
    path.write_text(path.read_text() + "\nEdited in vim.\n", encoding="utf-8")

    with pytest.raises(Conflict) as exc:
        write_entry(
            kb_of(project),
            "fact",
            "acme-new",
            FACT,
            "From the browser.",
            base_hash=content_hash("stale"),
        )
    # Both versions come back so the UI can compare rather than just refuse.
    assert "Edited in vim." in exc.value.current


def test_a_correct_base_hash_succeeds(project: Path) -> None:
    first = write_entry(kb_of(project), "fact", "acme-new", FACT, "First.")
    second = write_entry(kb_of(project), "fact", "acme-new", FACT, "Second.", base_hash=first.hash)
    assert "Second." in second.path.read_text()


# -- step 4: round-trip ----------------------------------------------------


def test_comments_in_frontmatter_survive_a_save(project: Path) -> None:
    """The bootstrap leaves `TODO: expand` notes in frontmatter. A PyYAML
    round trip eats them and the loss is invisible."""
    raw = (
        "---\n"
        "id: acme-new\n"
        "# this note must survive\n"
        "type: fact\n"
        "parent: acme-engineer\n"
        "title: With a comment\n"
        "tags: [python]\n"
        "depth: working\n"
        "verifiable: true\n"
        "visibility: public\n"
        "---\n\nBody.\n"
    )
    write_entry(kb_of(project), "fact", "acme-new", raw)
    stored = read_entry(kb_of(project), "fact", "acme-new")

    again = write_entry(
        kb_of(project),
        "fact",
        "acme-new",
        stored["frontmatter"],
        stored["body"],
        base_hash=stored["hash"],
    )
    assert "# this note must survive" in again.path.read_text()


# -- step 5: atomicity -----------------------------------------------------


def test_no_temp_file_is_left_behind(project: Path) -> None:
    write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.")
    assert list((kb_of(project) / "facts").glob("*.tmp")) == []


# -- deletion --------------------------------------------------------------


def test_a_referenced_entry_cannot_be_deleted(project: Path) -> None:
    """A dangling parent leaves facts that render nowhere — silently."""
    write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.")
    with pytest.raises(StillReferenced, match="acme-new"):
        delete_entry(kb_of(project), "role", "acme-engineer")


def test_an_unreferenced_entry_deletes_with_history(project: Path) -> None:
    write_entry(kb_of(project), "fact", "acme-new", FACT, "Body.")
    assert delete_entry(kb_of(project), "fact", "acme-new")
    assert not (kb_of(project) / "facts" / "acme-new.md").exists()


# -- the raw editor uses the same path -------------------------------------


def test_the_raw_editor_cannot_bypass_validation(project: Path) -> None:
    """It exists to express what the structured form cannot, not to skip rules."""
    raw = (
        "---\nid: acme-new\ntype: fact\nparent: ghost\ntitle: Raw\n"
        "tags: [python]\ndepth: working\nverifiable: true\nvisibility: public\n---\n\nB.\n"
    )
    with pytest.raises(ValidationFailed):
        write_entry(kb_of(project), "fact", "acme-new", raw)
