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
from .escape import TexSafe, UnescapedContent, escape_tex, tex_raw

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
DEFAULT_TEMPLATE = "resume.tex.j2"


@dataclass(frozen=True)
class Geometry:
    """Page metrics, measured from the source PDF rather than guessed.

    The source is A4 (595x842pt) produced by Google Docs, with a 36pt left
    margin and text running to x=581 — a right margin of roughly 0.2in. That
    asymmetry is reproduced here as a symmetric 0.5in instead: a 0.2in right
    margin risks clipping on print, and the cost is a text column about 4%
    narrower, against roughly 65pt of unused vertical space on the source page.

    Every value is a template parameter, so matching the source exactly is a
    constructor argument rather than an edit.
    """

    font_size: int = 11
    left: str = "0.5in"
    right: str = "0.5in"
    top: str = "0.5in"
    bottom: str = "0.5in"
    section_before: str = "10pt"
    section_after: str = "3pt"
    header_after: str = "-4pt"
    entry_gap: str = "3pt"
    #: Muted blue, close to the source's hyperlink colour.
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
