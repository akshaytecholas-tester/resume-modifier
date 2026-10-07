"""LaTeX escaping (spec-05 §3.1).

Every string here appears in the source resume or its date lines, so these are
regression tests against real content rather than invented edge cases.
"""

from __future__ import annotations

import pytest

from resume_tailor.render.escape import (
    TEX_ESCAPES,
    TexSafe,
    escape_tex,
    join_tex,
    tex_raw,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C# (.NET Core)", r"C\# (.NET Core)"),
        ("40% faster", r"40\% faster"),
        ("AI & Data Engineering", r"AI \& Data Engineering"),
        ("snake_case", r"snake\_case"),
        ("$100", r"\$100"),
        ("{braced}", r"\{braced\}"),
        ("~approx", r"\textasciitilde{}approx"),
        ("x^2", r"x\textasciicircum{}2"),
        ("95%+ first-pass", r"95\%+ first-pass"),
        ("2,000+ concurrent", "2,000+ concurrent"),
    ],
)
def test_reserved_characters(raw: str, expected: str) -> None:
    assert str(escape_tex(raw)) == expected


def test_backslash_is_not_double_escaped() -> None:
    """The failure spec-05 §3.1 warns about.

    A sequential replace chain rewrites `\\` to `\\textbackslash{}` and then
    escapes the braces it just introduced, producing
    `\\textbackslash\\{\\}`. One regex pass cannot, because a replacement is
    never rescanned.
    """
    assert str(escape_tex("a\\b")) == r"a\textbackslash{}b"
    assert "\\{" not in str(escape_tex("a\\b"))


def test_every_reserved_character_is_covered() -> None:
    for char in TEX_ESCAPES:
        assert str(escape_tex(char)) == TEX_ESCAPES[char]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Classify → Retrieve → Generate",
            r"Classify $\rightarrow$ Retrieve $\rightarrow$ Generate",
        ),
        ("Feb 2026 – Present", "Feb 2026 -- Present"),
        ("Consultant — xpar.in", "Consultant --- xpar.in"),
        ("“Captain Extraordinary”", "``Captain Extraordinary''"),
        ("zero​width", "zerowidth"),
        ("non breaking", "non~breaking"),
    ],
)
def test_unicode_is_translated_not_passed_through(raw: str, expected: str) -> None:
    """Keeps the generated .tex ASCII so it compiles under any engine.

    A raw U+2192 compiles here, where Tectonic runs XeTeX, and fails for
    someone whose Overleaf project is set to pdfLaTeX — which AC-R7.2 forbids.
    """
    assert str(escape_tex(raw)) == expected


def test_output_is_ascii_for_realistic_content() -> None:
    body = "Architected RAG pipelines (Classify → Retrieve → Generate) — 50% faster"
    str(escape_tex(body)).encode("ascii")  # raises if any byte survived untranslated


def test_escaping_is_idempotent() -> None:
    once = escape_tex("a & b")
    assert escape_tex(once) == once


def test_none_becomes_empty() -> None:
    assert str(escape_tex(None)) == ""


def test_result_is_marked_safe() -> None:
    assert isinstance(escape_tex("x"), TexSafe)
    assert not isinstance("x", TexSafe)


def test_tex_raw_is_not_escaped() -> None:
    assert str(tex_raw(r"\href{a}{b}")) == r"\href{a}{b}"
    assert isinstance(tex_raw("x"), TexSafe)


def test_join_escapes_items_but_not_the_separator() -> None:
    assert str(join_tex(["a&b", "c%d"], " | ")) == r"a\&b | c\%d"


def test_numbers_are_accepted() -> None:
    assert str(escape_tex(40)) == "40"


# -- inline bold -----------------------------------------------------------


def test_markup_bolds_and_still_escapes() -> None:
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("serving **2,000+ users** & more")) == (
        r"serving \textbf{2,000+ users} \& more"
    )


def test_markup_ignores_loose_asterisks() -> None:
    """`a ** b ** c` is arithmetic or emphasis the author did not intend."""
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("a ** b ** c")) == "a ** b ** c"


def test_markup_cannot_inject_latex() -> None:
    """Content inside `**` is escaped before the bold wrapper is applied, so a
    fact body cannot smuggle a macro through it."""
    from resume_tailor.render.escape import markup_tex

    out = str(markup_tex(r"**\input{/etc/passwd}**"))
    assert r"\textbackslash{}input" in out
    assert r"\input{" not in out


def test_markup_italicises() -> None:
    """The source italicises parentheticals — "(Coursework: ...)" after the
    degree, "(Jun 2024)" after an internship."""
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("CUSAT *(Coursework: DSA)*")) == r"CUSAT \textit{(Coursework: DSA)}"


def test_bold_and_italic_together() -> None:
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("**9.13 / 10** *(top decile)*")) == (
        r"\textbf{9.13 / 10} \textit{(top decile)}"
    )


def test_italic_pass_does_not_eat_half_a_bold_marker() -> None:
    """Bold runs first, so by the italic pass no `**` remains to be misread."""
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("**bold** and plain")) == r"\textbf{bold} and plain"


def test_lone_asterisk_is_left_alone() -> None:
    from resume_tailor.render.escape import markup_tex

    assert str(markup_tex("2 * 3 = 6")) == "2 * 3 = 6"
