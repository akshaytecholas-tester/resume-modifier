# resume-tailor

A local, single-user system that tailors a resume to a job description from a complete personal career knowledge base — then shows what matched, what's missing, and lets you revise by chat before exporting a PDF.

**Status:** implementation underway. The specification is complete and merged; the knowledge base layer is built. See [Milestones](#milestones).

## The problem it solves

Manual resume tailoring fails in two directions. Over-claiming is visible and gets punished in interviews. **Silent omission** — a genuinely relevant project you simply didn't think of while editing — is invisible, and you never learn which application it cost you.

Eliminating silent omission is the point. Everything else is mechanism.

## Read in this order

| Document | What it answers |
|---|---|
| [docs/PRD.md](docs/PRD.md) | What is being built, for whom, and what counts as done |
| [docs/traceability.md](docs/traceability.md) | Did every stated requirement survive into the design? **Review this first.** |
| [docs/spec-01-knowledge-base.md](docs/spec-01-knowledge-base.md) | How career data is stored and edited |
| [docs/spec-02-agent-pipeline.md](docs/spec-02-agent-pipeline.md) | The five agents and why selection reads everything |
| [docs/spec-03-runtime-auth.md](docs/spec-03-runtime-auth.md) | Subscription vs API key, and the spike that decides it |
| [docs/spec-04-api-and-ui.md](docs/spec-04-api-and-ui.md) | Endpoints, the write path, the screens |
| [docs/spec-05-latex-rendering.md](docs/spec-05-latex-rendering.md) | LaTeX generation and PDF output |
| [docs/spec-06-provider-backends.md](docs/spec-06-provider-backends.md) | Running on providers other than Claude |
| [docs/spec-07-applications-and-tracker.md](docs/spec-07-applications-and-tracker.md) | Application archive, tracker, dual contact sets |
| [docs/open-questions.md](docs/open-questions.md) | What's still undecided and what each answer blocks |

`traceability.md` is the fast review surface: every requirement appears there alongside the user's own words that produced it. If something asked for isn't in that table, the PRD is incomplete.

## Three invariants

These are load-bearing, and all three are easy to regress toward their opposite:

1. **Tags never gate retrieval.** Selection reads the full text of every fact. Tags exist for human navigation, audit trails, and second-pass validation. A missing tag must never cause a silent miss.
2. **The knowledge base is the source of truth; LaTeX is generated from it.** Agents edit structured data, never `.tex`.
3. **Every claim traces to a recorded fact.** A validator with no stake in making the resume look good cuts anything that doesn't.

## Local setup

```bash
brew install tectonic                 # LaTeX engine, ~70MB (needed from M2 on)
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Then create the knowledge base. **It is not in this repository**, by design:

```bash
mkdir -p kb/{roles,facts,projects,blogs,education,certifications,awards}
cp kb/identity.example.yaml kb/identity.yaml
$EDITOR kb/identity.yaml              # name, contact sets, links
git init kb                           # versioning, with NO remote — see below
.venv/bin/rt kb validate
```

### Why `kb/` has its own git repository

This repository is **public**. `kb/` holds a complete career record — every
employer, location, date and achievement, plus the working notes written
against them. None of that should be indexable under its owner's name.

But the design needs git: history, diff and one-click revert come from commits
rather than from a hand-rolled undo stack (AC-R8.3, [spec-04 §3](docs/spec-04-api-and-ui.md)),
and three different writers touch those files — the browser, a text editor, and
agent-proposed changes.

So `kb/` is versioned by its own repository, which has **no remote**. Both
properties hold at once: full history locally, nothing published. The outer
`.gitignore` excludes everything under `kb/` except `identity.example.yaml`,
which a fresh clone needs.

**Do not add a remote to `kb/`.** That single action is what would publish the
career record, and nothing else in the design prevents it.

### What else stays local

| Path | Why |
|---|---|
| `kb/` | The career record, and `identity.yaml`'s contact details |
| `applications/` | Complete resumes, job descriptions, third-party referrer names |
| `runs/` | Disposable tailoring output; reproducible from `kb/` |
| `evidence/` | Certificates and letters |
| `*.pdf`, `*.docx` | Source resumes dropped in for bootstrapping |

Durability for all of these comes from being plain files in a backed-up home
directory, not from version control ([open-questions OQ-3](docs/open-questions.md)).

## Using it

```bash
.venv/bin/rt kb validate      # the ten rules of spec-01 §4
.venv/bin/rt kb stats         # corpus size and shape — the numbers OQ-2 tracks
.venv/bin/rt kb index         # rebuild .cache/index.json; safe at any time
```

## Milestones

| | Milestone | State |
|---|---|---|
| M1 | Knowledge base: schema, loader, validation, bootstrap | **done** |
| M2 | LaTeX template and PDF output | next |
| M3 | Runner backends behind one interface | |
| M4 | The five-agent pipeline, end to end from a CLI | |
| M5 | FastAPI write path and SSE | |
| M6 | React UI | |
| M7 | Application archive and tracker | |

## Tests

```bash
.venv/bin/pytest -q            # live-backend tests are excluded by default
.venv/bin/pytest -q -m live    # hits a real model backend
.venv/bin/ruff check src tests
```

## Validating the docs

```bash
python3 docs/validate_docs.py
```

Stdlib only. Fails on untraced requirements, acceptance criteria without Given/When/Then, specs covering undefined requirements, orphaned criteria, missing source quotes, and dead links.

## Next step

M2: the LaTeX template, reproducing the source resume's layout from the
knowledge base so the output is familiar rather than merely correct
([spec-05 §4](docs/spec-05-latex-rendering.md)).
