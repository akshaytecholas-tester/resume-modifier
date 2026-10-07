#!/usr/bin/env python3
"""Compare a rendered resume against its source PDF, numerically.

spec-05 §4 originally described checking fidelity by rendering both to PNG and
comparing by eye. That catches gross structural differences and misses
everything else: a heading one point too large, a measure 4% narrow, a baseline
off by half a point. All three move line breaks, and none is visible side by
side.

So this measures instead. For each element it reports the source's rendered
width, the candidate's, and the ratio — and because glyph width scales linearly
with font size, that ratio *is* the correction factor:

    corrected_size = current_size * (source_width / rendered_width)

Elements are derived from the document's own shape rather than listed, so this
works on any resume and holds nobody's name.

Needs poppler (`pdftotext -bbox`).

    python3 scripts/fidelity.py SOURCE.pdf RENDERED.pdf
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
)
PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)"')

#: Positional elements at the top of a resume, in document order.
POSITIONAL = ("name", "headline", "contact")

#: The `Geometry` field that corrects each kind of element.
KNOBS = {
    "name": "name_size",
    "headline": "headline_size",
    "contact": "contact_size",
    "heading": "heading_size",
}

#: Deviation below this is reported but not flagged. Residual at this scale is
#: glyph-width difference between a Times clone and the real font, not a size
#: error — a size error would be uniform and single-signed.
TOLERANCE = 0.01


@dataclass(frozen=True)
class Line:
    y: float
    x0: float
    x1: float
    text: str

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def extract(path: str) -> tuple[tuple[float, float], list[Line]]:
    xml = subprocess.run(
        ["pdftotext", "-bbox", path, "-"], capture_output=True, text=True, check=True
    ).stdout

    page = PAGE.search(xml)
    size = (float(page.group(1)), float(page.group(2))) if page else (0.0, 0.0)

    # Grouped per page, not by y alone: y restarts at every page break, so a
    # single key merged a heading on page 2 with a body line on page 1 and
    # reported a 471pt heading.
    grouped: dict[tuple[int, float], list[tuple[float, float, str]]] = {}
    for page_no, chunk in enumerate(xml.split("<page ")):
        for x0, y0, x1, _y1, text in WORD.findall(chunk):
            grouped.setdefault((page_no, round(float(y0))), []).append((float(x0), float(x1), text))

    lines = []
    for (_page, y), words in sorted(grouped.items()):
        words.sort()
        lines.append(
            Line(
                y=y,
                x0=min(w[0] for w in words),
                x1=max(w[1] for w in words),
                text=" ".join(w[2] for w in words),
            )
        )
    return size, lines


def normalise(text: str) -> str:
    """Strip entities and punctuation so one element matches across two
    renderers that disagree about quoting and dashes."""
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")
    # Whitespace collapsed, not merely stripped: removing `&` from
    # "EDUCATION & CERTIFICATIONS" leaves a double space, and a key joined with
    # single spaces then failed to match it.
    return " ".join(re.sub(r"[^a-z0-9 ]+", "", text.lower()).split())


#: Words of the source line used to locate it in the candidate.
#:
#: A prefix rather than the whole line, because the two documents legitimately
#: differ further along: the contact line's phone spacing and link text come
#: out of two renderers differently, and requiring a full match reported the
#: line as absent rather than comparing it.
MATCH_WORDS = 3


def find(lines: list[Line], needle: str) -> Line | None:
    key = " ".join(normalise(needle).split()[:MATCH_WORDS])
    if not key:
        return None
    for line in lines:
        if normalise(line.text).startswith(key):
            return line
    return None


def decode(text: str) -> str:
    return text.replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")


def is_heading(line: Line) -> bool:
    """A section heading: set in caps, and short enough not to be a sentence.

    Entities are decoded first — `&amp;` contains lowercase letters, so
    "EDUCATION & CERTIFICATIONS" failed the caps test and was skipped.
    """
    text = decode(line.text)
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and len(text) < 48


def elements(lines: list[Line]) -> list[tuple[str, Line]]:
    """Comparable elements, derived from the document rather than listed.

    Taking the first three lines positionally and the rest by shape keeps this
    reusable. An earlier version listed the author's name as a literal, which
    worked for exactly one document and put their name in a tracked file of a
    public repository.
    """
    found: list[tuple[str, Line]] = [
        (kind, lines[i]) for i, kind in enumerate(POSITIONAL) if i < len(lines)
    ]
    # The name is set in caps too, so it would otherwise be counted twice —
    # once positionally and once as a section heading.
    claimed = {id(line) for _, line in found}
    found.extend(("heading", ln) for ln in lines if is_heading(ln) and id(ln) not in claimed)
    return found


def modal_gap(lines: list[Line]) -> float:
    """The most common baseline-to-baseline distance.

    The modal gap, not the minimum: a glyph extracted onto its own line
    produces a 1pt gap that is not a baseline at all, and taking the minimum
    reports that instead of the body leading.
    """
    gaps = [lines[i + 1].y - lines[i].y for i in range(len(lines) - 1)]
    real = [g for g in gaps if g > 2]  # a page break reads as a negative gap
    return max(set(real), key=real.count) if real else 0.0


def main(source_path: str, candidate_path: str) -> int:
    (sw, sh), source = extract(source_path)
    (cw, ch), candidate = extract(candidate_path)

    print(f"page      source {sw:.1f} x {sh:.1f}    candidate {cw:.1f} x {ch:.1f}")

    s_block = (min(ln.x0 for ln in source), max(ln.x1 for ln in source))
    c_block = (min(ln.x0 for ln in candidate), max(ln.x1 for ln in candidate))
    print(
        f"text x    source {s_block[0]:.1f} -> {s_block[1]:.1f}"
        f"    candidate {c_block[0]:.1f} -> {c_block[1]:.1f}"
    )
    print(
        f"measure   source {s_block[1] - s_block[0]:.1f}bp"
        f"    candidate {c_block[1] - c_block[0]:.1f}bp"
    )
    print()

    print(f"{'element':<26}{'source':>9}{'render':>9}{'ratio':>8}  {'knob':<16}")
    print("-" * 72)
    worst = 0.0
    for kind, line in elements(source):
        label = (
            (normalise(line.text)[:24] or "(blank)").upper()
            if kind == "heading"
            else (normalise(line.text)[:24] or "(blank)")
        )
        # Matched by text, never by position. A hyperlinked contact line is
        # extracted as several runs at slightly different y, so the candidate's
        # third line is not reliably the candidate's contact line.
        other = find(candidate, line.text)

        if other is None or not other.width:
            print(f"{label:<26}{line.width:>9.1f}{'-':>9}{'':>8}  not in the render")
            continue

        ratio = line.width / other.width
        worst = max(worst, abs(1 - ratio))
        flag = "" if abs(1 - ratio) < TOLERANCE else "  <-- adjust"
        print(
            f"{label:<26}{line.width:>9.1f}{other.width:>9.1f}{ratio:>8.3f}  "
            f"{KNOBS[kind]:<16}{flag}"
        )

    print()
    print(f"baseline  source {modal_gap(source):.1f}bp    candidate {modal_gap(candidate):.1f}bp")
    print(f"lines     source {len(source)}        candidate {len(candidate)}")
    print()
    print(f"worst element deviation: {worst * 100:.1f}%")
    return 0 if worst < TOLERANCE else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
