# Open Questions

Each entry names the decision it blocks and when it must be answered. An open question with no blocked decision is just trivia and doesn't belong here.

---

## OQ-1 — Does the Agent SDK accept a Pro/Max subscription session?

**Blocks:** default `RunnerBackend`; whether an API key and a cost budget are needed at all.
**Resolve by:** implementation step 1, before any other code.
**Method:** [spec-03 §3](spec-03-runtime-auth.md) spike protocol.

Documentation is genuinely ambiguous. Acceptable use says Pro/Max limits "assume ordinary, individual usage of Claude Code **and the Agent SDK**", while the SDK docs steer developers to API keys and bar routing requests "on behalf of their users". A single-user local tool is not the latter — but third-party reports describe server-side enforcement, and reading documentation is not the same as running the code.

**Record on resolution** — dated, because enforcement behavior can change and an undated answer is worthless in six months:

```
Date tested:
SDK without API key:   [ok | failed]   error:
CLI subprocess:        [ok | failed]   error:
Backend selected:
```

---

## OQ-2 — At what corpus size does full-corpus selection stop working?

**Blocks:** whether semantic search is ever needed; the point at which [spec-02 §2](spec-02-agent-pipeline.md) must be revisited.
**Resolve by:** ongoing measurement, not up front.

Current design reads every fact on every selection pass, which is right at ~150 facts (~18K tokens) and clearly wrong at 5,000. The threshold is unknown and depends on both cost and whether selection quality degrades with corpus size — the second being the one that actually matters, since degradation is silent.

**Signals to watch:** corpus token count (reported by `/api/health`); per-run cost; whether Recall starts finding more omissions as the corpus grows, which would indicate the Selector is losing track rather than that Recall is working well.

Provisional trigger to re-examine: **500 entries or 100K corpus tokens**, whichever first. Picked as an order-of-magnitude marker, not a measured threshold.

---

## OQ-3 — Is `runs/` git-tracked?

**Blocks:** `.gitignore` contents; repo size growth.

**For tracking:** a record of every application and what was sent, which is genuinely useful when a recruiter calls back about a resume sent three months ago.
**Against:** compiled PDFs are binary and inflate the repo; most runs are throwaway experiments.

**Leaning:** track the text artifacts (`posting.txt`, `analysis.json`, `selection.json`, `draft.json`, `chat.jsonl`), ignore `*.pdf` and `*.tex` since both are reproducible from the artifacts. Needs confirmation.

---

## OQ-4 — One page or two?

**Blocks:** Writer length budget; overflow behavior in [spec-05 §6](spec-05-latex-rendering.md).

The current resume is one page at ~2.2 years of experience, which is conventional. As the record grows, forcing one page starts cutting relevant content — and silent cutting to fit is the exact failure the product exists to prevent.

**Needs a policy:** is one page a hard constraint, a default with per-run override, or a target the user resolves manually each time via the overflow report? Current spec assumes the third, which is the safest default but asks the most of the user.

---

## OQ-5 — Can NDA-flagged content appear in any export?

**Blocks:** `visibility` enforcement strictness in [spec-05 §7](spec-05-latex-rendering.md).

Current spec: `visibility: nda` content is selectable and visible in review (it's the user's own history) but the renderer refuses to emit it.

**Unresolved:** whether there's a legitimate middle case — generalizing an NDA-bound achievement so it conveys capability without identifying the client ("built document ingestion for a Fortune 500 financial services client"). That is normal resume practice and is probably wanted, but it needs an explicit mechanism: likely a `generalized` field holding a pre-approved safe phrasing, with the renderer emitting that instead of refusing.

Until decided, the strict rule stands. Over-blocking is recoverable; leaking isn't.

---

## OQ-6 — Which model for which agent?

**Blocks:** cost per run; nothing structural.

[spec-02 §5](spec-02-agent-pipeline.md) assigns provisionally: strongest model for Analyst, Selector, Recall, and Writer; a smaller model for the Validator, which is a checking task.

**Untested assumption:** that a smaller model is adequate for validation. It might be *better* — less inclined to rationalize a claim into being supported — or materially worse at noticing subtle unsupported inference. Worth an A/B once there's a real corpus and a few real drafts to check against.

---

## Resolved

| # | Question | Decision | Date |
|---|---|---|---|
| — | Voice input in v1? | No — text chat only; voice deferred to v2 | 2026-10-06 |
| — | Single PRD or PRD + specs? | PRD + five companion specs | 2026-10-06 |
| — | Commit to one runtime backend? | No — pluggable interface, spike decides the default | 2026-10-06 |
| — | Vector DB for the KB? | No — full-corpus selection; revisit per OQ-2 | 2026-10-06 |
| — | Tags as the retrieval mechanism? | No — tags are for humans and audit; selection is semantic over full content | 2026-10-06 |
| — | LaTeX as source of truth? | No — KB is source of truth; LaTeX is generated | 2026-10-06 |
