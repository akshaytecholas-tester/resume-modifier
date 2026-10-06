"""Path containment (spec-04 §2 step 2).

An entry id becomes a filesystem path. Without containment, an id like
`../../../.ssh/authorized_keys` is an arbitrary-write primitive on the user's
own machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.kb.paths import PathEscape, contain, entry_path, repo_root


def test_entry_path_for_each_type(tmp_path: Path) -> None:
    assert entry_path(tmp_path, "fact", "a-b").name == "a-b.md"
    assert entry_path(tmp_path, "fact", "a-b").parent.name == "facts"
    assert entry_path(tmp_path, "role", "a").parent.name == "roles"
    assert entry_path(tmp_path, "certification", "az-900").parent.name == "certifications"


@pytest.mark.parametrize(
    "hostile_id",
    [
        "../../../etc/passwd",
        "../../.ssh/authorized_keys",
        "..",
        "/etc/passwd",
        "a/../../b",
        "a/b",
        "a\\b",
        ".",
        "",
        "a.md",
        "A-B",
        "a--b",
        "-a",
        "a-",
        "a b",
        "a\x00b",
    ],
)
def test_traversal_and_non_slug_ids_are_refused(tmp_path: Path, hostile_id: str) -> None:
    with pytest.raises(PathEscape):
        entry_path(tmp_path, "fact", hostile_id)


def test_unknown_type_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown type"):
        entry_path(tmp_path, "sandwich", "a")


def test_contain_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(PathEscape):
        contain(Path("../outside"), tmp_path)


def test_contain_allows_nested(tmp_path: Path) -> None:
    assert contain(Path("facts/a.md"), tmp_path) == (tmp_path / "facts" / "a.md").resolve()


def test_contain_rejects_absolute_outside(tmp_path: Path) -> None:
    with pytest.raises(PathEscape):
        contain(Path("/etc/passwd"), tmp_path)


def test_repo_root_finds_the_kb_ancestor(tmp_path: Path) -> None:
    (tmp_path / "kb").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert repo_root(nested) == tmp_path.resolve()
