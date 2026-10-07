"""Tectonic invocation and the overflow report (spec-05 §2, §6)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from resume_tailor.render.compile import (
    CompileError,
    _explain,
    available,
    check_overflow,
    compile_pdf,
    healthcheck,
    page_count,
)
from resume_tailor.render.document import Bullet, Contact, Document, Entry, Section
from resume_tailor.render.latex import render_document

TECTONIC = pytest.mark.skipif(not available(), reason="tectonic is not installed")


def test_healthcheck_reports_engine_and_cache() -> None:
    report = healthcheck()
    assert set(report) == {"tectonic", "path", "version", "cache_warm"}


def test_error_is_located_in_the_source() -> None:
    """AC-R6.2: a compile failure names the offending source line."""
    source = "\\documentclass{article}\n\\begin{document}\n\\badmacro\n\\end{document}\n"
    log = "/tmp/x.tex:3: Undefined control sequence \\badmacro"
    error = _explain(log, source)
    assert error.line == 3
    assert "badmacro" in (error.source_line or "")


def test_tex_style_line_echo_is_also_understood() -> None:
    """Failures inside a package report `l.NN` rather than `file:NN`."""
    error = _explain("! Undefined control sequence.\nl.7 \\nope", "a\nb\nc\nd\ne\nf\ng\n")
    assert error.line == 7


def test_unparseable_log_still_produces_a_message() -> None:
    error = _explain("something went wrong with no line number", "x\n")
    assert error.line is None
    assert str(error)


def test_error_message_is_not_a_traceback() -> None:
    error = CompileError("Undefined control sequence", 3, "\\badmacro")
    rendered = str(error)
    assert "line 3" in rendered and "badmacro" in rendered
    assert "Traceback" not in rendered


def _document(bullets_per_entry: int = 2) -> Document:
    return Document(
        contact=Contact(name="Ada Lovelace", email="ada@example.com"),
        contact_set="default",
        sections=(
            Section(
                heading="Professional Experience",
                kind="entries",
                entries=(
                    Entry(
                        title="Engineer",
                        org="Acme",
                        dates="Jan 2024 – Present",
                        bullets=tuple(
                            Bullet(lead=f"Lead {i}", text="Did the thing.")
                            for i in range(bullets_per_entry)
                        ),
                    ),
                ),
            ),
        ),
    )


# -- overflow is reported, never cut --------------------------------------


def test_within_budget_reports_no_overflow() -> None:
    from resume_tailor.render.compile import CompileResult

    report = check_overflow(CompileResult(pdf=Path("x.pdf"), pages=1), _document(), budget=1)
    assert not report.over
    assert "within" in report.summary()


def test_overflow_names_candidates_and_removes_nothing() -> None:
    """spec-05 §6. Dropping content to fit is the silent omission this product
    exists to prevent, so the report says so in as many words."""
    from resume_tailor.render.compile import CompileResult

    doc = _document(bullets_per_entry=3)
    report = check_overflow(CompileResult(pdf=Path("x.pdf"), pages=2), doc, budget=1)
    assert report.over
    assert len(report.candidates) == 3
    assert "nothing has been removed" in report.summary()
    # The document is untouched.
    assert len(doc.sections[0].entries[0].bullets) == 3


def test_candidates_are_oldest_last_bullets_first() -> None:
    from resume_tailor.render.compile import CompileResult

    doc = _document(bullets_per_entry=3)
    report = check_overflow(CompileResult(pdf=Path("x.pdf"), pages=2), doc, budget=1)
    assert report.candidates[0][1] == "Lead 2"


# -- the real engine -------------------------------------------------------


@TECTONIC
def test_compiles_a_real_document(tmp_path: Path) -> None:
    tex = tmp_path / "resume.tex"
    tex.write_text(render_document(_document()), encoding="utf-8")
    result = compile_pdf(tex, tmp_path)
    assert result.pdf.is_file() and result.pdf.stat().st_size > 0
    assert result.pages == 1


@TECTONIC
def test_a_broken_document_raises_and_leaves_no_stub(tmp_path: Path) -> None:
    """A zero-byte PDF that opens blank is worse than an error: it looks like
    it worked."""
    tex = tmp_path / "broken.tex"
    tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\undefinedmacro\n\\end{document}\n",
        encoding="utf-8",
    )
    with pytest.raises(CompileError):
        compile_pdf(tex, tmp_path)
    assert not (tmp_path / "broken.pdf").exists()


@TECTONIC
def test_page_count_matches_pdfinfo(tmp_path: Path) -> None:
    tex = tmp_path / "resume.tex"
    tex.write_text(render_document(_document()), encoding="utf-8")
    result = compile_pdf(tex, tmp_path)
    assert page_count(result.pdf) == result.pages


@TECTONIC
def test_page_count_fallback_agrees_with_poppler(tmp_path: Path, monkeypatch) -> None:
    """poppler is a convenience here, not a declared dependency, so the
    fallback has to give the same answer."""
    tex = tmp_path / "resume.tex"
    tex.write_text(render_document(_document()), encoding="utf-8")
    pdf = compile_pdf(tex, tmp_path).pdf
    with_poppler = page_count(pdf)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert page_count(pdf) == with_poppler
