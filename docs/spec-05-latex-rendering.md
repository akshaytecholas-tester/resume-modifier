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

Reproducing `resume_amalkrishn_m_u_ai_python_dev.pdf` (inventory in [PRD](PRD.md) §9):

| Element | Target |
|---|---|
| Page | US Letter, single column, ~0.5in margins |
| Header | Name centered, large; role subtitle beneath |
| Contact | Single pipe-separated line; email and links hyperlinked |
| Section headings | Small caps, horizontal rule beneath |
| Section order | Summary · Technical Skills · Professional Experience · Internships · Education & Certifications |
| Experience entry | Title — Org \| Location on the left, dates right-aligned on the same line |
| Bullets | Bold lead-in phrase, then detail — the pattern throughout the current resume |
| Skills | Grouped bullets with bold group labels |
| Font | Serif body, ~10–11pt |

Built on `article` with `geometry`, `titlesec`, `enumitem`, and `hyperref`. No resume class — `moderncv` and friends impose their own visual identity, and the requirement is to match an existing document rather than adopt a new look.

### Verification

Since poppler is installed, fidelity is checked visually rather than by eye-memory:

```bash
pdftoppm -png -r 150 resume_amalkrishn_m_u_ai_python_dev.pdf /tmp/orig
pdftoppm -png -r 150 runs/<slug>/resume.pdf /tmp/new
# compare /tmp/orig-1.png against /tmp/new-1.png
```

Section order, column structure, and bullet style must match. Exact font metrics will not, since the original is a word-processor export — that difference is accepted (RK-4).

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

- **`export.pdf`** — compiled output (AC-R6.1). Compile failure returns the Tectonic error with the offending source line, never an empty file (AC-R6.2).
- **`export.tex`** — self-contained source, preamble inlined, no local `\input`, so it compiles in Overleaf unmodified (AC-R7.2).

Both are written into `runs/<slug>/` and remain reproducible from the artifacts there.

**Render-time `visibility` enforcement:** the renderer asserts no `visibility: nda` or `private` content appears in the output, and fails the render rather than emitting it (RK-7). This check lives here — at the last gate before content leaves the machine — rather than at selection, where it would hide the user's own history from them during review.
