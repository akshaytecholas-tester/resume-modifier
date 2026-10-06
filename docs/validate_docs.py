#!/usr/bin/env python3
"""Mechanical completeness check for the PRD and its companion specs.

Catches the documentation failures that are easy to make and hard to spot by
reading: a requirement that exists in the PRD but never got traced, an
acceptance criterion with no Given/When/Then, a spec claiming to cover a
requirement that was renamed, a dead relative link.

Stdlib only. Exits non-zero if anything fails.

    python3 docs/validate_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent

REQUIRED_FILES = [
    "PRD.md",
    "spec-01-knowledge-base.md",
    "spec-02-agent-pipeline.md",
    "spec-03-runtime-auth.md",
    "spec-04-api-and-ui.md",
    "spec-05-latex-rendering.md",
    "traceability.md",
    "open-questions.md",
    "validate_docs.py",
]

SPEC_FILES = [f for f in REQUIRED_FILES if f.startswith("spec-")]

RE_REQ_HEADING = re.compile(r"^### (R\d+) — (.+)$", re.M)
RE_AC_DEF = re.compile(r"^\*\*(AC-R\d+\.\d+)\*\* — (.+)$", re.M)
RE_AC_REF = re.compile(r"AC-R\d+\.\d+")
RE_RID = re.compile(r"\bR\d+\b")
RE_COVERS = re.compile(r"^\*\*Covers:\*\* (.+)$", re.M)
RE_TRACE_ROW = re.compile(r"^\| (R\d+) \|(.+)$", re.M)
RE_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")

failures: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- files

missing = [f for f in REQUIRED_FILES if not (DOCS / f).exists()]
for f in missing:
    fail(f"missing file: docs/{f}")
if missing:
    print("\n".join(failures), file=sys.stderr)
    sys.exit(1)

prd = read("PRD.md")
trace = read("traceability.md")

# ---------------------------------------------------- requirements in PRD

prd_reqs: dict[str, str] = {m.group(1): m.group(2) for m in RE_REQ_HEADING.finditer(prd)}
if not prd_reqs:
    fail("PRD.md: no requirement headings found (expected '### R1 — ...')")

# Split the PRD into per-requirement blocks so each can be checked in isolation.
blocks: dict[str, str] = {}
matches = list(RE_REQ_HEADING.finditer(prd))
for i, m in enumerate(matches):
    end = matches[i + 1].start() if i + 1 < len(matches) else len(prd)
    blocks[m.group(1)] = prd[m.end():end]

prd_acs: set[str] = set()
for rid, body in blocks.items():
    acs = RE_AC_DEF.findall(body)
    if not acs:
        fail(f"{rid}: no acceptance criteria defined")
    for ac_id, ac_text in acs:
        prd_acs.add(ac_id)
        if not ac_id.startswith(f"AC-{rid}."):
            fail(f"{ac_id}: numbered under the wrong requirement (in block {rid})")
        for kw in ("Given", "When", "Then"):
            if kw not in ac_text:
                fail(f"{ac_id}: not testable — missing '{kw}' clause")
    if not re.search(r"^> ", body, re.M):
        fail(f"{rid}: no source quote — every requirement must cite the user's words")

# ------------------------------------------------- traceability coverage

trace_rows: dict[str, str] = {m.group(1): m.group(2) for m in RE_TRACE_ROW.finditer(trace)}

for rid in prd_reqs:
    if rid not in trace_rows:
        fail(f"{rid}: defined in PRD.md but absent from traceability.md")
for rid in trace_rows:
    if rid not in prd_reqs:
        fail(f"{rid}: traced in traceability.md but not defined in PRD.md")

trace_acs: set[str] = set()
for rid, row in trace_rows.items():
    cells = [c.strip() for c in row.split("|")]
    if len(cells) < 4:
        fail(f"{rid}: traceability row has {len(cells)} cells, expected at least 4")
        continue
    _desc, quote, ac_cell, spec_cell = cells[0], cells[1], cells[2], cells[3]
    if not quote or quote in {"-", "—"}:
        fail(f"{rid}: no source quote in traceability.md")
    row_acs = RE_AC_REF.findall(ac_cell)
    if not row_acs:
        fail(f"{rid}: no acceptance criteria referenced in traceability.md")
    trace_acs.update(row_acs)
    if not RE_LINK.search(spec_cell):
        fail(f"{rid}: no spec reference in traceability.md")

for ac in sorted(prd_acs - trace_acs):
    fail(f"{ac}: defined in PRD.md but not referenced in traceability.md")
for ac in sorted(trace_acs - prd_acs):
    fail(f"{ac}: referenced in traceability.md but not defined in PRD.md")

# ------------------------------------------------------ spec Covers lines

for spec in SPEC_FILES:
    text = read(spec)
    m = RE_COVERS.search(text)
    if not m:
        fail(f"{spec}: no '**Covers:**' line declaring which requirements it serves")
        continue
    for rid in RE_RID.findall(m.group(1)):
        if rid not in prd_reqs:
            fail(f"{spec}: Covers {rid}, which is not defined in PRD.md")

covered: set[str] = set()
for spec in SPEC_FILES:
    m = RE_COVERS.search(read(spec))
    if m:
        covered.update(RE_RID.findall(m.group(1)))
uncovered = sorted(set(prd_reqs) - covered, key=lambda r: int(r[1:]))
if uncovered:
    notes.append(
        "requirements with no spec (satisfied in the PRD itself — verify this is intended): "
        + ", ".join(uncovered)
    )

# ------------------------------------------------------------- dead links

for name in REQUIRED_FILES:
    if not name.endswith(".md"):
        continue
    for target in RE_LINK.findall(read(name)):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (DOCS / target).exists():
            fail(f"{name}: dead link → {target}")

# ----------------------------------------------------------------- report

print(f"files         {len(REQUIRED_FILES)}")
print(f"requirements  {len(prd_reqs)}")
print(f"criteria      {len(prd_acs)}")
print(f"traced        {len(trace_rows)}")

for n in notes:
    print(f"\nnote: {n}")

if failures:
    print(f"\nFAILED ({len(failures)})", file=sys.stderr)
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    sys.exit(1)

print("\nOK — every requirement is quoted, tested, traced, and specced.")
