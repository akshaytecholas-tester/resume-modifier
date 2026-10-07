"""Jinja2 configured for LaTeX, and the guard that makes escaping provable.

LaTeX is **generated, never authored** (spec-05 §1). No agent writes `.tex`: a
model editing LaTeX directly produces a document that fails to compile on an
unescaped `&`, and the failure arrives at export time with no clean recovery.
Generating it means the output is either valid or the template has a bug — a
class of failure fixed once rather than per run.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import jinja2

from ..kb.identity import Identity
from ..kb.loader import Corpus
from .document import Document, build_baseline
from .escape import TexSafe, UnescapedContent, escape_tex, markup_tex, tex_raw

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
DEFAULT_TEMPLATE = "resume.tex.j2"


@dataclass(frozen=True)
class Geometry:
    """Page metrics, taken from the source PDF by measurement.

    **These are the author's design, not a starting point.** The source resume
    is a deliberate layout the user tailored to their own preference, so every
    value here reproduces it rather than improving on it. Measured with
    `pdfinfo` and `pdftotext -bbox`:

    | Measured | Value |
    |---|---|
    | Page | A4, 595.28 x 841.89pt |
    | Text block | x 36.0 -> 581.0, width 545pt |
    | Margins | left 36pt, right 14.28pt — asymmetric, and intentionally so |
    | Body | 11pt, 13pt baseline-to-baseline |
    | Bullet | glyph at x=54, text at x=72 |

    The asymmetry is the author's and is reproduced exactly. An earlier version
    of this file "corrected" it to symmetric 0.5in margins on the grounds that a
    0.2in right margin risks print clipping. That was not a call to make
    unasked: it narrowed the measure by 4% and silently changed where every
    line broke.

    Sizes are explicit point values rather than `\\LARGE`-style names, because
    those resolve relative to the body size and cannot express a measured
    target.

    **Everything here is in `bp`, never `pt`.** A PDF point is 1/72 inch, which
    TeX calls a *big point*; TeX's own `pt` is 1/72.27 inch. Writing a measured
    `595.28` as `pt` produced a 593.06pt page — every length and every glyph
    0.37% small, uniformly enough to look like a font-metric difference rather
    than a unit bug.
    """

    #: A4 exactly, as the source reports it.
    paper_width: str = "595.28bp"
    paper_height: str = "841.89bp"

    left: str = "36bp"
    #: 595.28 - 36 - 545 = 14.28bp of right margin. Asymmetric, as the source is.
    text_width: str = "545bp"
    top: str = "36bp"
    bottom: str = "36bp"

    #: Class option, which only accepts 10/11/12. The real body size is
    #: `body_size` below, applied explicitly so it can be stated in `bp`.
    font_size: int = 11
    body_size: str = "11bp"
    baseline: str = "13bp"

    #: Checked against the source's rendered widths by `scripts/fidelity.py`.
    #:
    #: Deliberately round numbers. The remaining deviation is under 0.7%, is
    #: non-uniform and runs in both directions (the headline renders 0.7% wide,
    #: the contact line 0.7% narrow), which is the signature of glyph-width
    #: differences between `newtx` and the Times New Roman the source embeds —
    #: not of a wrong size, which would be uniform and single-signed.
    #:
    #: Nudging these to fractional values would zero the measurement by baking
    #: a font-substitution artifact in as though it were a design decision, and
    #: would then be wrong for anyone compiling with the real font.
    name_size: str = "16bp"
    name_baseline: str = "19bp"
    headline_size: str = "12bp"
    headline_baseline: str = "14bp"
    contact_size: str = "10bp"
    contact_baseline: str = "12bp"
    heading_size: str = "12bp"
    heading_baseline: str = "14bp"

    section_before: str = "13bp"
    section_after: str = "2bp"
    header_after: str = "0bp"
    entry_gap: str = "2bp"

    #: Bullet list metrics, from the glyph at x=54 and text at x=72, so the
    #: glyph sits 18bp into the text block and the text 36bp in.
    list_indent: str = "36bp"
    label_width: str = "9bp"
    label_sep: str = "9.2bp"
    item_sep: str = "0bp"
    #: The source sets its bullets in Arial as U+25CF, 8.8bp wide. Times'
    #: \textbullet is 3.85bp, visibly smaller, so it is scaled to match rather
    #: than left as a different mark from the one the author chose.
    bullet_scale: str = "2.29"
    bullet_raise: str = "-3.7bp"

    #: Muted grey for dates and the location, as the source uses.
    muted_gray: str = "0.40"
    #: Link colour, sampled from the source's hyperlinks.
    link_rgb: str = "30,80,160"

    def as_context(self) -> dict[str, TexSafe]:
        """Template-authored constants, emitted verbatim.

        Safe to mark raw because these are code, not knowledge-base content —
        and they are typed as LaTeX lengths, which escaping would break.
        """
        return {f.name: tex_raw(str(getattr(self, f.name))) for f in fields(self)}


def _finalize(value: Any) -> Any:
    """Refuse to output anything that has not been escaped.

    This is the mechanism behind spec-05 §3's render-time assertion. `TexSafe`
    is a `str` subclass, so `isinstance(x, str)` cannot tell escaped content
    from raw — the check has to be the other way round.

    Without it a forgotten `|tex` is invisible until some fact body happens to
    contain an `&`, which for this corpus means "AI & Data Engineering" on the
    very first render.
    """
    if value is None:
        return ""
    if isinstance(value, TexSafe):
        return value
    if isinstance(value, bool):
        raise UnescapedContent("a boolean reached the template; use \\BLOCK{if} instead")
    if isinstance(value, int | float):
        return value
    raise UnescapedContent(
        f"unescaped value of type {type(value).__name__} reached the template: "
        f"{str(value)[:60]!r}. Every content variable must end with `|tex`."
    )


def build_environment(template_dir: Path | None = None) -> jinja2.Environment:
    """Jinja with LaTeX-safe delimiters (spec-05 §3).

    Jinja's `{{ }}` and `{% %}` collide with LaTeX's own braces; without the
    alternatives below the template is unreadable and brace-fragile.

    `autoescape=False` because Jinja's escaper is for HTML and would produce
    `&amp;` in a `.tex` file. Escaping is the explicit `tex` filter instead,
    enforced by `_finalize`.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir or TEMPLATE_DIR),
        block_start_string="\\BLOCK{",
        block_end_string="}",
        variable_start_string="\\VAR{",
        variable_end_string="}",
        comment_start_string="\\#{",
        comment_end_string="}",
        line_statement_prefix="%%-",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        finalize=_finalize,
        keep_trailing_newline=True,
    )
    env.filters["tex"] = escape_tex
    env.filters["markup"] = markup_tex
    return env


def _contact_parts(doc: Document) -> list[TexSafe]:
    """The pipe-separated contact line, with email and links made clickable.

    Built here rather than in the template because each part needs a different
    LaTeX wrapper, and expressing that in Jinja would mean a chain of
    conditionals around content that still has to be escaped individually.
    """
    parts: list[TexSafe] = []
    contact = doc.contact

    if contact.location:
        parts.append(escape_tex(contact.location))
    if contact.phone:
        parts.append(escape_tex(contact.phone))
    if contact.email:
        parts.append(tex_raw(rf"\href{{mailto:{contact.email}}}{{{escape_tex(contact.email)}}}"))
    for _, url in contact.links:
        href = url if url.startswith(("http://", "https://")) else f"https://{url}"
        parts.append(tex_raw(rf"\href{{{href}}}{{{escape_tex(url)}}}"))
    return parts


def render_document(
    doc: Document,
    *,
    geometry: Geometry | None = None,
    template: str = DEFAULT_TEMPLATE,
    template_dir: Path | None = None,
) -> str:
    """Render one `Document` to LaTeX source."""
    env = build_environment(template_dir)
    return env.get_template(template).render(
        doc=doc,
        contact_parts=_contact_parts(doc),
        geometry=(geometry or Geometry()).as_context(),
    )


def render_baseline(
    corpus: Corpus,
    identity: Identity,
    contact_set: str,
    *,
    summary: str | None = None,
    geometry: Geometry | None = None,
) -> tuple[Document, str]:
    """Build and render the whole knowledge base for one contact set."""
    doc = build_baseline(corpus, identity, contact_set, summary=summary)
    return doc, render_document(doc, geometry=geometry)
