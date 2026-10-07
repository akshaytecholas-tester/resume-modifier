# Spec 05 — LaTeX Rendering

**Covers:** R6, R7
**Related:** [PRD](PRD.md) · [KB](spec-01-knowledge-base.md)

---

## 1. Position

"Overleaf format" is LaTeX — Overleaf is a hosted editor, not a file format. The deliverable is a `.tex` file that compiles locally and can be pasted into Overleaf unmodified (AC-R7.2).

**LaTeX is generated, never authored.** The pipeline is:

```
KB facts ──▶ Writer ──▶ draft.json ──▶ Jinja2 ──▶ resume.tex ──▶ Tectonic ──▶ PDF
```

Agents produce structured content; the template produces LaTeX. No agent edits `.tex`. A model editing LaTeX directly produces a document that fails to compile on an unescaped `&` or an unbalanced brace, and the failure arrives at export time with no clean recovery. Keeping LaTeX generated means output is either valid or the template has a bug — a class of failure that is fixed once rather than per run.

## 2. Engine: Tectonic

`brew install tectonic` — single binary, ~70MB, fetches packages on demand and caches them.

Rejected: MacTeX (~5GB for a single-document use case), and a Docker LaTeX image (a container runtime dependency for a tool whose whole premise is running locally and simply).

Tectonic's on-demand fetch means the **first** compile needs network access. Subsequent compiles are offline. The health endpoint reports whether Tectonic is present and whether its package cache is warm, so a missing engine surfaces at startup rather than at the moment the user wants a PDF.

```bash
tectonic --outdir runs/<slug>/ runs/<slug>/resume.tex
```

## 3. Template

`templates/resume.tex.j2`, rendered with Jinja2 configured for LaTeX:

```python
latex_env = jinja2.Environment(
    block_start_string='\\BLOCK{',  block_end_string='}',
    variable_start_string='\\VAR{', variable_end_string='}',
    comment_start_string='\\#{',    comment_end_string='}',
    trim_blocks=True, lstrip_blocks=True, autoescape=False,
)
latex_env.filters['tex'] = escape_tex
```

Jinja's default `{{ }}` and `{% %}` collide with LaTeX's own braces. The alternative delimiters above are the standard resolution; without them the template is unreadable and brace-fragile.

`autoescape=False` because Jinja's HTML escaper is wrong for LaTeX — escaping is done by the explicit `tex` filter instead, which every content variable must pass through.

### 3.1 Escaping

```python
TEX_ESCAPES = {
    '\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$',
    '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
}
```

Backslash is substituted first, or it would double-escape the replacements. Applied to every interpolated value (AC-R7.3) — "C# (.NET Core)" and "40% faster" both appear in the existing resume, so this is exercised immediately, not hypothetically.

A render-time assertion rejects any content variable that reached the template without passing the filter, so the omission is caught in tests rather than at export.

## 4. Fidelity targets

**The source resume is the specification, not a starting point.** It is a
layout the author tailored to their own preference, so the renderer reproduces
it rather than improving on it. Changes to type, spacing or margins happen only
when the author asks for them.

Everything below is **measured** from `resume_amalkrishn_m_u_ai_python_dev.pdf`
with `pdfinfo` and `pdftotext -bbox`, replacing an earlier version of this
section that was written from memory of the document and was wrong in four
places — it claimed US Letter, small-caps headings with a horizontal rule, and
dates right-aligned on the title line. None of those is what the document does.

| Element | Measured |
|---|---|
| Page | A4, 595.28 x 841.89bp |
| Text block | x 36.0 → 581.0, measure 545bp |
| Margins | left 36bp, right 14.28bp — **asymmetric** |
| Body | Times New Roman 11bp, 13bp baseline-to-baseline, justified |
| Name | 16bp bold, all caps, centred on the text block (x=308.5, not the page's 297.6) |
| Headline | 12bp bold, centred |
| Contact | 10bp, grey, pipe-separated, email and links hyperlinked in blue |
| Section headings | 12bp bold, all caps, **no rule, not small caps** |
| Experience entry | Bold title, em dash, org, then grey `\| location` |
| Dates | **Their own line beneath the title**, grey italic — not right-aligned |
| Bullets | Arial-style black circle 8.82bp wide, glyph at x=54, text at x=72 |
| Bullet text | Bold lead-in phrase, colon, then detail |
| Emphasis | Key figures bolded inline within prose and bullets |

The asymmetric margin is the author's and is reproduced exactly. An earlier
implementation "corrected" it to a symmetric 0.5in on the grounds that a 0.2in
right margin risks clipping on print. That was not a call to make unasked: it
narrowed the measure by 4% and silently moved every line break.

Built on `article` with `geometry`, `titlesec`, `enumitem`, `graphicx`,
`xcolor` and `hyperref`. No resume class — `moderncv` and friends impose their
own visual identity, and the requirement is to match an existing document.

`newtxtext` supplies a Times clone metrically compatible with the Times New
Roman the source embeds. Using the real font via `fontspec` would match
exactly on this machine and fail in Overleaf, where it is not installed —
which AC-R7.2 forbids.

### 4.1 Lengths are `bp`, never `pt`

A PDF point is 1/72 inch, which TeX calls a **big point** (`bp`). TeX's own
`pt` is 1/72.27 inch.

Writing a measured `595.28` as `pt` produced a 593.06pt page: every length and
every glyph 0.37% small. The error is uniform, so it reads as a font-metric
difference rather than a unit bug, and nothing about the output looks wrong
until it is measured. Every value in `Geometry` is therefore `bp`, and a test
asserts it.

### 4.2 Verification is numeric

```bash
python3 scripts/fidelity.py <source>.pdf runs/baseline/resume-<set>.pdf
```

Reports page size, text block, measure, baseline and per-element rendered
widths, with the ratio against the source. Because glyph width scales linearly
with font size, that ratio **is** the correction factor.

Comparing PNG renders by eye — which this section previously specified — catches
gross structural differences and misses a heading one point too large, a measure
4% narrow, or a baseline off by half a point. All three move line breaks.

Current state: page, text block, measure, baseline and bullet geometry match
exactly. Per-element widths are within **0.7%**, and that residual is left
alone deliberately: it is non-uniform and runs in both directions, which is the
signature of glyph-width differences between `newtx` and real Times New Roman.
Tuning it away with fractional font sizes would encode a substitution artifact
as a design value, and be wrong for anyone compiling with the real font.

## 5. Links and ATS

`hyperref` with `hidelinks` — clickable, not colored boxes.

ATS parseability constrains the design, since many applications pass through a parser before a human:

- Single column. Multi-column layouts interleave badly when linearized.
- No text in graphics, no icon fonts for contact details.
- Standard section headings ("Professional Experience", not "Where I've Been").
- Real bullet lists, not manual glyphs.
- Dates as text in the flow, not in a sidebar.

The existing resume already satisfies these, which is a point in favor of reproducing rather than redesigning it.

## 6. Length

Target one page. `draft.json` carries a length budget, and the Writer is given a bullet quota per role derived from it.

Overflow is handled by **reporting, not silent truncation**: the renderer measures the compiled page count and, if over budget, returns the overflow to the UI with the lowest-scoring bullets identified as cut candidates. The user decides. Dropping content automatically to fit a page is a silent omission — the precise failure this product exists to prevent (PRD §1).

Two pages are permitted when the user chooses; the policy question of when that's appropriate is [open-questions.md](open-questions.md) OQ-4.

## 7. Export

The renderer takes a `contact_set` argument naming a set in `identity.yaml` ([spec-01 §2.1](spec-01-knowledge-base.md)), and **export produces one resume per configured set** — `resume-referral.*`, `resume-direct.*` (R17). Only the contact block differs; the tailored body is byte-identical, since the pipeline runs once (AC-R17.3). With one set configured, one file is produced (AC-R17.4).

- **`export.pdf`** — compiled output (AC-R6.1). Compile failure returns the Tectonic error with the offending source line, never an empty file (AC-R6.2).
- **`export.tex`** — self-contained source, preamble inlined, no local `\input`, so it compiles in Overleaf unmodified (AC-R7.2).

Both are written into `runs/<slug>/` and remain reproducible from the artifacts there.

**Render-time `visibility` enforcement:** the renderer asserts no `visibility: nda` or `private` content appears in the output, and fails the render rather than emitting it (RK-7). This check lives here — at the last gate before content leaves the machine — rather than at selection, where it would hide the user's own history from them during review.
