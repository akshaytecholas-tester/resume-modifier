# Spec 01 — Knowledge Base

**Covers:** R8, R9, R10, R13
**Related:** [PRD](PRD.md) · [Agents](spec-02-agent-pipeline.md) · [API/UI](spec-04-api-and-ui.md)

---

## 1. Principles

**P1 — Plain files are the state.** There is no database and no canonical copy elsewhere. Editing in the web UI, editing in vim, and an agent proposing a change are three paths to the same bytes on disk. (R8)

**P2 — The KB is a superset.** Fact bodies are written in *more* detail than any resume would use. Detail omitted from the KB can never be selected; detail included costs nothing, because the Writer compresses per JD. (R9)

**P3 — Atomicity below the role.** A job is a container of independently selectable achievements. The unit of selection is the achievement, not the job. (R11.4)

**P4 — `kb/` is authored; `runs/` is generated.** A run may propose a KB change; only an approved write path applies it. `runs/` can be deleted entirely without loss.

**P5 — Tags describe, they do not gate.** Tags are written for humans and for audit. No retrieval step filters on them. (R10, R11)

## 2. Directory layout

```
resume-tailor/
├── kb/                          # authored truth — git-tracked
│   ├── identity.yaml            # name, contact, links (PII, isolated)
│   ├── taxonomy.yaml            # controlled vocabulary
│   ├── skills.yaml              # declared proficiency → evidence fact ids
│   ├── roles/                   # employment containers
│   │   ├── ey-ase1.md
│   │   ├── ey-ase2.md
│   │   └── xpar-consultant.md
│   ├── facts/                   # atomic achievements → parent
│   │   ├── ey-ase2-rag.md
│   │   ├── ey-ase2-ingestion.md
│   │   ├── ey-ase2-debugging.md
│   │   ├── ey-ase2-promotion.md
│   │   ├── xpar-trading-engine.md
│   │   ├── xpar-ledger-acid.md
│   │   └── xpar-edge-delivery.md
│   ├── projects/
│   ├── blogs/
│   ├── education/
│   ├── certifications/
│   └── awards/
├── profiles/                    # saved weightings (ai-dev, backend, …)
├── runs/                        # generated per JD — disposable
├── evidence/                    # cert PDFs, letters (gitignored)
└── .cache/                      # derived, rebuildable
```

`identity.yaml` is separate because it is the only PII-dense file; isolating it makes it trivial to exclude if the repo is ever pushed to a remote.

## 3. Entry schemas

### 3.1 Role (container)

```markdown
---
id: ey-ase2
type: role
title: Associate Software Engineer 2 (Python & AI)
org: EY GDS
location: Kochi
dates: {start: 2025-08, end: 2026-02}
employment: full-time
visibility: public
tags: [python, azure, ai, enterprise]
---

Scope and context for the role as a whole. Team shape, what the org did,
what was owned. Not achievements — those are facts with `parent: ey-ase2`.
```

A role carries no bullets. It supplies the heading, dates, and org that selected facts render beneath.

### 3.2 Fact (atomic achievement)

```markdown
---
id: xpar-trading-engine
type: fact
parent: xpar-consultant
title: Event-driven pub/sub trading engine
tags: [go, websockets, postgres, event-driven, realtime, fintech, low-latency]
metrics:
  - {value: "sub-100ms", what: "order matching latency"}
  - {value: "2,000+", what: "concurrent users sustained"}
depth: expert
verifiable: true
visibility: public
related: [xpar-ledger-acid]
locked_phrasing: null
---

Engineered the matching engine as a Go pub/sub system over WebSockets with
Postgres persistence. Order book held in memory with a write-ahead path to
Postgres; margin recalculated per fill rather than per tick, which is what
kept p99 under 100ms at 2k connections. Backpressure handled by dropping
stale market-data frames while never dropping order-state frames.
```

### 3.3 Field reference

| Field | Type | Required | Purpose |
|---|---|---|---|
| `id` | slug | yes | Stable identity. Never renumbered; filename mirrors it. |
| `type` | enum | yes | `role` `fact` `project` `blog` `education` `certification` `award` |
| `parent` | id | facts only | Which role/project this achievement belongs under |
| `title` | string | yes | Short human label for UI lists and audit output |
| `tags` | [slug] | yes | Must exist in `taxonomy.yaml` |
| `metrics` | [{value, what}] | no | Structured so the Writer can reuse without retyping numbers |
| `depth` | enum | yes | `expert` \| `working` \| `exposure` — caps how strongly this may be framed |
| `verifiable` | bool | yes | Whether the claim is provable if challenged |
| `visibility` | enum | yes | `public` \| `nda` \| `private` |
| `related` | [id] | no | Cross-links, shown to the user during review |
| `locked_phrasing` | string\|null | no | Approved wording the Writer must not rewrite |
| `dates` | {start, end} | roles/projects | `YYYY-MM`; `end: present` allowed |

**`depth` is a ceiling, not a label.** The Writer is instructed that an `exposure` fact may be mentioned but never framed as expertise, and the Validator flags violations. This is the structural defense against over-claiming (Q3).

**`visibility` is enforced at render, not selection.** An `nda` fact may be selected and shown to the user in review — it's their own history — but the renderer refuses to emit it. Enforcing at selection would hide the user's own data from themselves; enforcing at render is where the actual leak risk is. (RK-7)

### 3.4 Blog / external project

```markdown
---
id: blog-rag-chunking
type: blog
title: Why fixed-size chunking fails on tabular PDFs
url: https://xpar.in/blog/rag-chunking
published: 2026-03-14
tags: [rag, chunking, document-processing, writing]
depth: working
verifiable: true
visibility: public
snapshot: snapshots/blog-rag-chunking.txt
---

Summary of the argument, plus why it demonstrates relevant capability.
```

The `snapshot` file holds extracted body text. Selection must never depend on a live fetch (AC-R9.3) — URLs rot, and the pipeline should work offline.

### 3.5 `skills.yaml`

```yaml
- skill: rag
  depth: expert
  evidence: [ey-ase2-rag, blog-rag-chunking]
- skill: go
  depth: working
  evidence: [xpar-trading-engine]
```

Every declared skill must cite ≥1 evidence fact id. A skill with no evidence is exactly where resume inflation lives, so `validate` rejects it rather than letting it through silently.

### 3.6 `taxonomy.yaml`

```yaml
rag:
  label: RAG Pipelines
  facet: skill
  aliases: [retrieval augmented generation, vector search, semantic search,
            grounded generation, document qa, knowledge retrieval]
celery:
  label: Celery
  facet: tech
  parent: async-python
  aliases: [task queue, async workers, background jobs, distributed tasks]
fintech:
  label: Financial Technology
  facet: domain
  aliases: [trading, payments, banking, ledger, financial services]
```

**Facets:** `skill` · `tech` · `domain` · `role-type` · `artifact-type` · `impact-type`.

Facets matter because a posting for "fintech backend" should match on domain even when the stack differs — a match that a flat tag list would miss.

**Aliases exist because job descriptions don't use your words.** A posting says "asynchronous task processing"; the entry is tagged `celery`. Aliases bridge that for the human-facing tag UI and the audit view. They do *not* constitute retrieval — the model reads the fact body regardless (R11).

## 4. Validation rules

Enforced on every write, before any byte reaches disk:

1. `id` matches `^[a-z0-9]+(-[a-z0-9]+)*$` and equals the filename stem.
2. `id` is unique across the whole KB.
3. `type` is a known value; required fields for that type are present.
4. `parent` resolves to an existing role or project.
5. Every tag exists in `taxonomy.yaml` — unknown tags return a warning the user resolves by adding to the vocabulary or correcting the tag (AC-R10.2), never a silent orphan.
6. `related` ids resolve.
7. `depth` and `visibility` are known enum values.
8. Dates parse as `YYYY-MM`; `start` ≤ `end`.
9. `skills.yaml` evidence ids resolve to existing entries.
10. No `metrics` entry has an empty `value` or `what`.

Failures return structured errors the UI renders per-field. An invalid entry is never written.

## 5. Writing and history

Every write is atomic (temp file + `os.replace` in the same directory) and followed by a git commit, message `kb: <verb> <id>`. This yields per-entry history, one-click revert, and a real diff when an agent proposes a change — with no undo stack to implement. Mechanics in [spec-04](spec-04-api-and-ui.md) §2.

Serialization uses `ruamel.yaml` in round-trip mode so key order, comments, and quoting survive. A naive `yaml.dump` would reformat frontmatter on every save and turn each UI edit into a large meaningless diff — which would destroy the value of the git history.

## 6. The derived index

`.cache/index.json` holds a compact row per entry (id, type, title, tags, parent, dates, token count). It is rebuilt from the files and is never authoritative.

**It is used for UI list rendering and for corpus statistics only.** It is explicitly *not* a retrieval surface: no agent selects from the index. This is written here because the index is precisely the thing that would tempt a future implementer back into lossy selection, which R11 forbids.

## 7. Bootstrap

The initial population comes from `resume_amalkrishn_m_u_ai_python_dev.pdf` (inventory in [PRD](PRD.md) §9): 3 roles, 9 facts, 2 internships, 1 degree, 1 certification, 1 award, plus a seeded taxonomy covering the technologies named there.

Bootstrap produces a *starting point*, not a finished KB. Resume bullets are compressed; fact bodies should be expanded with the detail the resume had to cut (P2). The UI's KB browser is where that expansion happens over time, including via chat (R13).
