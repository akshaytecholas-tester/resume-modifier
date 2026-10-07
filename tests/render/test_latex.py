"""The Jinja environment and its escaping guard (spec-05 §3)."""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

from resume_tailor.render.document import Bullet, Contact, Document, Section
from resume_tailor.render.escape import UnescapedContent
from resume_tailor.render.latex import Geometry, build_environment, render_document


def render_string(source: str, **context) -> str:
    env = build_environment()
    return env.from_string(source).render(**context)


def test_delimiters_do_not_collide_with_latex() -> None:
    """Jinja's `{{ }}` and `{% %}` collide with LaTeX's braces (spec-05 §3)."""
    out = render_string(r"\textbf{\VAR{name|tex}}", name="Ada")
    assert out == r"\textbf{Ada}"


def test_block_delimiter_works() -> None:
    out = render_string(r"\BLOCK{for x in xs}\VAR{x|tex},\BLOCK{endfor}", xs=["a&b", "c"])
    assert out == r"a\&b,c,"


def test_missing_tex_filter_raises() -> None:
    """The render-time assertion spec-05 §3 requires.

    Without it a forgotten `|tex` is invisible until some fact body contains an
    `&` — which for this corpus is "AI & Data Engineering", on the first render.
    """
    with pytest.raises(UnescapedContent, match="must end with `|tex`"):
        render_string(r"\VAR{name}", name="AI & Data")


def test_filter_order_is_enforced() -> None:
    """`|tex|upper` leaves a plain str, so the guard must still fire."""
    with pytest.raises(UnescapedContent):
        render_string(r"\VAR{name|tex|upper}", name="ada")


def test_tex_last_is_accepted() -> None:
    assert render_string(r"\VAR{name|upper|tex}", name="ada") == "ADA"


def test_numbers_pass_through() -> None:
    assert render_string(r"\VAR{n}", n=3) == "3"


def test_none_renders_empty() -> None:
    assert render_string(r"[\VAR{n}]", n=None) == "[]"


def test_booleans_are_refused() -> None:
    with pytest.raises(UnescapedContent, match="boolean"):
        render_string(r"\VAR{flag}", flag=True)


def test_undefined_is_strict() -> None:
    """A typo'd variable must fail, not silently render nothing."""
    with pytest.raises(jinja2.UndefinedError):
        render_string(r"\VAR{nope|tex}")


def test_geometry_reproduces_the_source_measurements() -> None:
    """These are the author's design, measured from their PDF, not defaults.

    Asserted here so a later "improvement" to the layout has to change a test
    that says why it exists.
    """
    g = Geometry()
    assert g.paper_width == "595.28bp" and g.paper_height == "841.89bp"
    assert g.left == "36bp" and g.text_width == "545bp"  # right margin 14.28bp
    assert g.body_size == "11bp" and g.baseline == "13bp"


def test_lengths_are_bp_never_pt() -> None:
    """A PDF point is 1/72in; TeX's `pt` is 1/72.27in.

    Writing a measured 595.28 as `pt` produced a 593.06pt page — every length
    0.37% small, uniformly enough to look like a font difference.
    """
    for field, value in vars(Geometry()).items():
        if isinstance(value, str) and value.rstrip("0123456789.").strip() == "pt":
            raise AssertionError(f"{field}={value!r} uses pt; measurements must be bp")


def test_geometry_values_are_emitted_verbatim() -> None:
    context = Geometry().as_context()
    # Template-authored lengths must not be escaped; the type marker is what
    # lets them past the guard at all.
    assert render_string(r"\VAR{g.left}", g=context) == "36bp"


def _document() -> Document:
    return Document(
        contact=Contact(
            name="Ada Lovelace",
            headline="Engineer & Analyst",
            location="London",
            email="ada@example.com",
            phone="+44 100",
            links=(("website", "ada.dev"),),
        ),
        contact_set="direct",
        sections=(
            Section(heading="Summary", kind="prose", prose="Built 100% of it."),
            Section(
                heading="Technical Skills",
                kind="bullets",
                bullets=(Bullet(lead="Languages", text="C#, Python"),),
            ),
        ),
    )


def test_full_template_renders_and_escapes() -> None:
    out = render_document(_document())
    assert r"Engineer \& Analyst" in out
    assert r"Built 100\% of it." in out
    assert r"C\#, Python" in out
    assert r"\documentclass[11pt]{article}" in out


def test_email_and_links_are_hyperlinked() -> None:
    out = render_document(_document())
    assert r"\href{mailto:ada@example.com}" in out
    assert r"\href{https://ada.dev}" in out


def test_template_is_self_contained() -> None:
    """AC-R7.2: it must compile in Overleaf unmodified.

    A local `\\input` or a bundled `.sty` would make the .tex useless the moment
    it is pasted somewhere else, which is the whole point of exporting it.
    """
    out = render_document(_document())
    assert "\\input{" not in out
    assert "\\include{" not in out
    assert out.count("\\documentclass") == 1
    assert "\\begin{document}" in out and "\\end{document}" in out


def test_empty_sections_are_dropped() -> None:
    doc = Document(
        contact=Contact(name="Ada"),
        contact_set="default",
        sections=(Section(heading="Empty", kind="bullets"),),
    )
    assert "EMPTY" not in render_document(doc)


def test_geometry_is_a_parameter(tmp_path: Path) -> None:
    out = render_document(_document(), geometry=Geometry(text_width="400bp", font_size=10))
    assert "textwidth=400bp" in out
    assert "[10pt]" in out
