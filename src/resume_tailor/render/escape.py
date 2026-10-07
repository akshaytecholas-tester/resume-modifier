"""LaTeX escaping (spec-05 §3.1).

Two jobs, and the second is the one that catches real bugs.

**Escaping.** Every interpolated value passes through `escape_tex`, which
rewrites the ten characters LaTeX treats specially plus the unicode punctuation
a word processor produces.

**Proving it happened.** `escape_tex` returns a `TexSafe` string, and the Jinja
environment refuses to output anything else (`latex.py`). A forgotten `|tex`
is then a render-time failure in the test suite rather than a compile error at
export, or — worse — a silently mangled document.
"""

from __future__ import annotations

import re
from typing import Any


class TexSafe(str):
    """A string that has been through `escape_tex`.

    The marker is the whole point: `isinstance(value, str)` cannot distinguish
    escaped content from raw content, so escaping gets its own type and the
    template environment checks for it.
    """

    __slots__ = ()


class UnescapedContent(RuntimeError):
    """A template tried to output a value that never passed through `tex`."""


#: The ten characters LaTeX reserves.
TEX_ESCAPES: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

#: Unicode punctuation a word processor emits, mapped to portable LaTeX.
#:
#: Translated rather than passed through so the generated `.tex` stays ASCII and
#: compiles unmodified under pdfLaTeX, XeLaTeX and LuaLaTeX — which is what
#: AC-R7.2 ("compiles in Overleaf unmodified") actually requires. Passing a raw
#: U+2192 through would compile here, where Tectonic runs XeTeX, and fail for
#: someone whose Overleaf project is set to pdfLaTeX.
UNICODE_ESCAPES: dict[str, str] = {
    "→": r"$\rightarrow$",  # →  appears in "Classify → Retrieve → Generate"
    "←": r"$\leftarrow$",
    "–": "--",  # –  en dash, used in every date range
    "—": "---",  # —  em dash, separates title from org
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
    "…": r"\ldots{}",
    "•": r"\textbullet{}",
    # Written as escapes deliberately: both are invisible in source, so a
    # literal would look like an empty or a duplicate key.
    "\u00a0": "~",  # non-breaking space
    "\u200b": "",  # zero-width space — Google Docs leaves these
    # in bullet text, where they survive every edit
    # because nothing renders differently
    "\u2033": r"\textquotedbl{}",  # the unpaired-quote sentinel, see below
    "−": "-",
    "×": r"$\times$",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
}

_ALL = {**TEX_ESCAPES, **UNICODE_ESCAPES}

#: Balanced pairs of ASCII double quotes, promoted to typographic ones.
#:
#: LaTeX renders a bare `"` as a RIGHT double quote, so `"Captain Extraordinary"`
#: comes out with two closing quotes. It is visibly wrong and easy to miss in
#: review, because it reads as a font quirk rather than a bug. Knowledge-base
#: bodies are written in a plain text editor and will contain ASCII quotes, so
#: this is handled here instead of being asked of the author.
_QUOTE_PAIR = re.compile(r'"([^"\n]*)"')

#: One regex alternation, longest-first, applied in a single pass.
#:
#: spec-05 §3.1 says to substitute the backslash first, because a sequential
#: `str.replace` chain would re-process the backslashes its own replacements
#: introduce. A single pass gives that guarantee structurally instead of by
#: ordering: every character is matched once and its replacement is never
#: rescanned, so no ordering can be got wrong later.
_PATTERN = re.compile("|".join(re.escape(k) for k in sorted(_ALL, key=len, reverse=True)))


def escape_tex(value: Any) -> TexSafe:
    """Escape a value for LaTeX. Idempotent, and safe on `None`."""
    if value is None:
        return TexSafe("")
    if isinstance(value, TexSafe):
        return value

    text = _QUOTE_PAIR.sub(lambda m: "\u201c" + m.group(1) + "\u201d", str(value))
    # Any unpaired `"` becomes an explicit vertical quote rather than silently
    # rendering as a closing one.
    text = text.replace('"', "\u2033")
    return TexSafe(_PATTERN.sub(lambda m: _ALL[m.group()], text))


def tex_raw(value: str) -> TexSafe:
    """Mark a string as LaTeX to emit verbatim, escaping nothing.

    For template-authored fragments only — never for knowledge-base content.
    It is deliberately awkward to reach for, because every use is a hole in the
    guarantee `TexSafe` otherwise provides.
    """
    return TexSafe(value)


def join_tex(values: list[Any], separator: str = ", ") -> TexSafe:
    """Escape each item, then join with an unescaped separator."""
    return TexSafe(separator.join(escape_tex(v) for v in values))


#: Inline `**bold**`, the one piece of markup knowledge-base bodies may carry.
#:
#: The source resume bolds key figures inside prose — "2,000+ concurrent users"
#: inside a bullet, "2.2+ years of experience" inside the summary — and that
#: emphasis is part of its design, not decoration.
#:
#: Safe to apply *after* escaping because `*` is not a LaTeX special character,
#: so it survives `escape_tex` untouched and nothing inside the braces can have
#: escaped conversion.
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)

#: Inline `*italic*`. The source uses it for parentheticals — "(Coursework:
#: C/C++, DSA, Networking, OS)" after the degree, "(Jun 2024)" after an
#: internship — so reproducing its design (R7) needs it.
#:
#: Applied after bold, by which point `**` pairs are already `\textbf{...}` and
#: their asterisks are gone, so a single-asterisk pass cannot mistake half of a
#: bold marker for an italic one.
_ITALIC = re.compile(r"(?<!\*)\*(?=\S)([^*]+?)(?<=\S)\*(?!\*)", re.S)


def markup_tex(value: Any) -> TexSafe:
    """Escape, then honour `**bold**` and `*italic*`.

    Deliberately the only two forms supported, because they are the only two
    the source document uses. Every additional form is another way for a fact
    body to produce LaTeX that nobody reviewed.
    """
    text = escape_tex(value)
    text = _BOLD.sub(lambda m: rf"\textbf{{{m.group(1)}}}", text)
    text = _ITALIC.sub(lambda m: rf"\textit{{{m.group(1)}}}", text)
    return TexSafe(text)
