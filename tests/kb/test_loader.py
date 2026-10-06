"""Frontmatter splitting and corpus assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.loader import ParseError, load_corpus, parse_entry, split_frontmatter
from resume_tailor.kb.yamlio import dump_yaml, parse_yaml


def test_split_basic() -> None:
    yaml_text, body = split_frontmatter("---\nid: a\n---\n\nBody text.\n")
    assert yaml_text == "id: a"
    assert body == "Body text.\n"


def test_body_containing_a_horizontal_rule_is_not_a_delimiter() -> None:
    """A `---` inside prose must not truncate the body.

    Markdown bodies legitimately contain horizontal rules, and splitting on the
    first one would silently drop everything after it — losing exactly the
    expansion detail the knowledge base exists to hold.
    """
    text = "---\nid: a\n---\n\nFirst part.\n\n---\n\nSecond part.\n"
    _, body = split_frontmatter(text)
    assert "Second part." in body


def test_missing_leading_delimiter() -> None:
    with pytest.raises(ValueError, match="does not start with"):
        split_frontmatter("id: a\n")


def test_unclosed_frontmatter() -> None:
    with pytest.raises(ValueError, match="never closed"):
        split_frontmatter("---\nid: a\n")


def test_parse_error_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("---\nid: broken\ntype: nonsense\n---\n\nx\n", encoding="utf-8")
    with pytest.raises(ParseError) as exc:
        parse_entry(path)
    assert exc.value.path == path
    assert "nonsense" in str(exc.value)


def test_corpus_collects_errors_without_raising(kb: Path) -> None:
    """One pass must report every broken file, not fail at the first."""
    (kb / "facts" / "bad.md").write_text("not frontmatter at all\n", encoding="utf-8")
    corpus = load_corpus(kb)
    assert len(corpus.parse_errors) == 1
    assert corpus.entries, "valid entries must still load"


def test_strict_mode_raises(kb: Path) -> None:
    (kb / "facts" / "bad.md").write_text("not frontmatter\n", encoding="utf-8")
    with pytest.raises(ParseError):
        load_corpus(kb, strict=True)


def test_corpus_order_is_stable_and_type_grouped(kb: Path) -> None:
    """Agent prompts cache the corpus as a stable prefix (spec-03 §6).

    Reordering between runs changes the prefix bytes and silently costs a full
    re-read on every call, so the order is pinned rather than incidental.
    """
    first = [e.id for e in load_corpus(kb).entries]
    second = [e.id for e in load_corpus(kb).entries]
    assert first == second
    types = [e.type for e in load_corpus(kb).entries]
    assert types == sorted(types, key=lambda t: ("role", "fact").index(t))


def test_facts_of_links_children_to_parent(kb: Path) -> None:
    corpus = load_corpus(kb)
    assert [e.id for e in corpus.facts_of("acme-engineer")] == ["acme-pipeline"]


def test_sha256_changes_with_content(kb: Path) -> None:
    before = load_corpus(kb).by_id()["acme-pipeline"].sha256
    path = kb / "facts" / "acme-pipeline.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nMore detail.\n", encoding="utf-8")
    assert load_corpus(kb).by_id()["acme-pipeline"].sha256 != before


def test_round_trip_preserves_comments_and_key_order() -> None:
    """The bootstrap leaves `TODO: expand` comments behind; they are content.

    A PyYAML round trip eats them, and that loss is invisible until someone
    notices their notes are gone.
    """
    source = "# leading note\nid: a\n# why this matters\ntype: fact\n"
    assert dump_yaml(parse_yaml(source)) == source
