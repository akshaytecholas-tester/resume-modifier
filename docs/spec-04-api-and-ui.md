# Spec 04 — API and UI

**Covers:** R1, R2, R4, R5, R8, R13, R14
**Related:** [PRD](PRD.md) · [KB](spec-01-knowledge-base.md) · [Agents](spec-02-agent-pipeline.md)

---

## 1. Shape

FastAPI process on `127.0.0.1:8000`, serving the built React bundle as static files and the API under `/api`. One process, one port, one command (AC-R14.1). In development, Vite runs separately and proxies `/api` to avoid a CORS configuration that would otherwise exist only to be a liability.

Binding is `127.0.0.1` explicitly, never `0.0.0.0` (AC-R1.2). This process has filesystem write access and an authenticated model session; exposing it to the LAN would hand both to anyone on the network.

## 2. The write path

Every byte that reaches `kb/` goes through these six steps, in order, regardless of whether the origin is the structured form, the raw editor, or an agent-proposed diff (AC-R13.3).

```
PUT /api/kb/{type}/{id}
      │
      1. pydantic validate ─────── spec-01 §4 rules; 422 with per-field errors
      2. path containment ──────── resolve, assert inside kb/, else 400
      3. base_hash check ───────── mismatch → 409 with current content
      4. ruamel round-trip ─────── preserve key order, comments, quoting
      5. atomic write ──────────── tmp in same dir + os.replace()
      6. git commit ────────────── "kb: update xpar-trading-engine"
      7. invalidate .cache/index
      │
      └─▶ 200 {new_hash, commit_sha}
```

**Why each step exists:**

- **Validate first** — an invalid entry never reaches disk, so the KB is never in a state the loader can't read.
- **Path containment** — the `id` becomes a path. Without resolving and asserting containment, an id like `../../../.ssh/authorized_keys` is an arbitrary-write primitive on the user's machine. Cheap check, severe omission.
- **`base_hash`** — there are genuinely three writers (browser, text editor, agents). Optimistic concurrency is what stops a UI save from silently destroying a vim edit made two minutes earlier (AC-R13.4).
- **Round-trip YAML** — `yaml.safe_dump` would strip comments and reorder keys, making every save a large diff and poisoning the git history that R8.3 depends on.
- **Atomic replace** — `os.replace` is atomic on APFS; a crash mid-write cannot leave a truncated career record.
- **Commit** — history, revert, and reviewable agent diffs for free.

## 3. Endpoints

### Knowledge base

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/kb/index` | All entries, compact, for list rendering |
| `GET` | `/api/kb/{type}/{id}` | One entry: parsed fields, raw text, `hash` |
| `POST` | `/api/kb/{type}` | Create |
| `PUT` | `/api/kb/{type}/{id}` | Update (requires `base_hash`) |
| `DELETE` | `/api/kb/{type}/{id}` | Delete (refused if referenced by `parent`/`related`/`evidence`) |
| `GET` | `/api/kb/{type}/{id}/history` | Commit log for this file |
| `POST` | `/api/kb/{type}/{id}/revert` | Restore a prior commit |
| `GET` `PUT` | `/api/taxonomy` | Controlled vocabulary |
| `POST` | `/api/kb/validate` | Dry-run validation, no write |

### Runs

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | Create from `{text}` or `{url}` → `run_id` |
| `GET` | `/api/runs` | List past runs |
| `GET` | `/api/runs/{id}` | All artifacts: requirements, selection, draft, validation |
| `GET` | `/api/runs/{id}/events` | **SSE** — live pipeline progress |
| `POST` | `/api/runs/{id}/chat` | Revision message → re-run Writer + Validator |
| `GET` | `/api/runs/{id}/export.pdf` | Compiled PDF |
| `GET` | `/api/runs/{id}/export.tex` | LaTeX source for Overleaf |
| `POST` | `/api/runs/{id}/kb-proposals/{pid}/accept` | Apply a proposed KB change via §2 |
| `POST` | `/api/runs/{id}/promote` | Freeze the run into an application ([spec-07 §9](spec-07-applications-and-tracker.md)) |

### Applications and tracker

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/applications` | Tracker list; filters for company, status, month, referral received |
| `GET` | `/api/applications/{id}` | One application: record, snapshot reference, artifact list |
| `PATCH` | `/api/applications/{id}` | Update status, stages, referral, `contact_set_sent` |
| `GET` | `/api/applications/{id}/snapshot` | The frozen content as sent |
| `GET` | `/api/applications/{id}/verify` | Re-hash artifacts, report drift |
| `POST` | `/api/applications/reindex` | Rebuild the SQLite index and `_views/` |

`PATCH` accepts only the mutable fields in [spec-07 §4.2](spec-07-applications-and-tracker.md); an attempt to modify a frozen field returns `409` naming the field, rather than being silently dropped.

### System

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Backend name, auth status, Tectonic presence, corpus size |
| `GET` | `/api/events` | **SSE** — KB file-change notifications |

`POST /api/runs` with a `url` returns the extracted text for confirmation and does **not** start the pipeline until confirmed (AC-R2.2); on a fetch failure it returns a specific error telling the user to paste (AC-R2.3).

## 4. SSE events

Two channels. Pipeline progress is per-run; KB changes are global.

```
event: stage
data: {"stage": "selector", "status": "running", "detail": "reading 147 facts"}

event: stage
data: {"stage": "selector", "status": "done", "tokens": {"in": 19204, "out": 1130, "cached": 18000}}

event: artifact
data: {"kind": "selection", "run_id": "2026-10-06-acme-ml-eng"}

event: error
data: {"stage": "writer", "message": "...", "resumable": true}
```

Streaming rather than polling (AC-R14.2). Stage events carry token counts so cost accrues visibly during the run instead of being discovered afterward.

## 5. Live reload from disk

A `watchdog` observer on `kb/` emits to `/api/events`, debounced ~200ms to coalesce the multiple filesystem events a single editor save produces. The UI reloads the affected entry (AC-R8.2).

If the changed entry is open in the editor **with unsaved local modifications**, the UI does not overwrite the draft — it shows a banner offering to reload or keep editing. Silently discarding typing because a file watcher fired would be worse than the conflict it's trying to prevent.

## 6. Screens

### 6.1 New run
JD paste box, URL field, profile selector. On URL submit: extracted text shown for confirmation, or a clear paste-instead message.

### 6.2 Run progress
The five stages with live status and token counts. Selector and Recall render side by side, since they run concurrently and the visual pairing communicates that they are two independent passes.

### 6.3 Review — the primary screen (R4)
Three panels:

- **Requirements → matches.** Each JD requirement with its matched facts, strength, selection reason, and tags (AC-R10.3). Facts chosen by only one of the two passes are badged `Selector only` / `Recall only` (AC-R12.2).
- **Gaps.** Requirements with no match, marked `absent` or `weak`. The genuinely actionable output — it says what to learn, what to address in a cover letter, or what KB fact is missing.
- **Draft.** The rendered resume, each bullet linking to its source fact ids, with `depth` shown so over-framing is visible.

Validator cuts and warnings appear inline, not hidden — a cut claim usually means a real fact is missing from the KB.

Export is disabled until this screen has been opened (AC-R4.3).

### 6.4 Chat
Conversation beside the draft. Each turn produces a diff on the draft (AC-R5.1). A request needing a nonexistent fact yields a proposed KB entry instead of a resume edit (AC-R5.2). Persisted to `runs/<slug>/chat.jsonl` and restored on reload (AC-R5.3).

### 6.5 KB browser and editor
List with facet filters and search; entry editor in two modes (AC-R13.1):

- **Structured** — tag chips with autocomplete over the taxonomy including alias hits (typing "vector search" offers `rag`), metrics as add/remove rows, `depth` and `visibility` as selects, body as a Markdown pane.
- **Raw** — the file text in a code editor, same validation on save.

Unknown tags prompt to add to the vocabulary rather than silently creating an orphan (AC-R10.2). A history panel per entry exposes the git log with revert.

### 6.6 Tracker (R19)
Sortable table over all applications — company, role, applied date, status, contact set sent, referral received, last stage. Filters for company, status, month, and referral. Status is editable inline; adding an interview stage opens a small form.

A status-pipeline summary sits above the table (how many at screening, interview, offer), because the count that matters when deciding whether to keep applying is how many are live, not how many were sent.

### 6.7 Application detail (R20)
The frozen record for one application: both resumes, the job description as applied against, the gap report, and the stage history.

The snapshot is shown **beside the current KB**, with facts whose text has changed since sending marked as diverged (AC-R20.4). That comparison is the feature — walking into a later-stage interview, what matters is what the interviewer read, and the diff shows exactly where today's KB would mislead you.

### 6.8 Proposals inbox
Agent-proposed KB changes — Recall's tag proposals (AC-R10.4), chat-derived new facts — as reviewable diffs. Accept routes through §2 like any other write.

## 7. Frontend

Vite + React + TypeScript + Tailwind. State: TanStack Query for server state, local component state otherwise — no global store, as nothing in this app justifies one.

For a single-user localhost tool, bundle size is not a real constraint; optimizing to Preact or Svelte would trade familiar tooling for a metric that doesn't bind here. The "light" requirement (R14) is met by avoiding a heavyweight framework and a build pipeline that needs maintenance, not by shaving kilobytes off a bundle served from localhost.

## 8. Errors

Every error response carries `{code, message, detail, remedy}`. The `remedy` is user-facing and specific: a LaTeX compile failure gives the source line (AC-R6.2); an auth failure names the backend and expected credential (AC-R15.3); a 409 returns both versions for comparison.
