"""The derived index (spec-01 §6). It is a cache, and nothing reads it as truth."""

from __future__ import annotations

import json
from pathlib import Path

from resume_tailor.kb.index import build_index, invalidate, write_index
from resume_tailor.kb.loader import load_corpus


def test_index_rows_cover_every_entry(kb: Path) -> None:
    corpus = load_corpus(kb)
    index = build_index(corpus)
    assert len(index["entries"]) == len(corpus.entries)
    assert index["counts"] == {"fact": 1, "role": 1}
    assert index["derived"] is True


def test_rebuild_is_idempotent(kb: Path, tmp_path: Path) -> None:
    cache = tmp_path / ".cache"
    corpus = load_corpus(kb)
    first = write_index(corpus, cache).read_text(encoding="utf-8")
    second = write_index(load_corpus(kb), cache).read_text(encoding="utf-8")
    assert first == second


def test_deleting_the_index_is_safe(kb: Path, tmp_path: Path) -> None:
    cache = tmp_path / ".cache"
    write_index(load_corpus(kb), cache)
    invalidate(cache)
    assert not (cache / "index.json").exists()
    invalidate(cache)  # second call must not raise
    assert write_index(load_corpus(kb), cache).exists()


def test_index_leaves_no_temp_file_behind(kb: Path, tmp_path: Path) -> None:
    cache = tmp_path / ".cache"
    write_index(load_corpus(kb), cache)
    assert list(cache.glob("*.tmp")) == []


def test_index_records_paths_relative_to_the_kb(kb: Path, tmp_path: Path) -> None:
    """Absolute paths would leak the user's home directory into a cache file."""
    index = build_index(load_corpus(kb))
    for row in index["entries"]:
        assert not Path(row["path"]).is_absolute()


def test_index_is_valid_json_with_a_token_estimate(kb: Path, tmp_path: Path) -> None:
    data = json.loads(write_index(load_corpus(kb), tmp_path / ".cache").read_text())
    assert data["estimated_corpus_tokens"] > 0
