"""Rendering the knowledge base into prompt text (spec-02 §2).

**Full fidelity, every time.** Selection receives every word of every fact
body, because relevance can hide in any clause and a summary is a lossy
projection whose loss is invisible. The temptation to send a compact index
instead is exactly what R11 forbids, so there is no "brief" mode here to
reach for.

The output is **stable**: the same corpus renders byte-identical every time,
which is what lets it serve as a cached prompt prefix (spec-03 §6). Any
instability — a dict iteration order, a timestamp, a set — would silently cost
a full re-read on every call.
"""

from __future__ import annotations

from ..kb.loader import Corpus, Entry

#: Fields shown above each body. Order is fixed, not derived from the model,
#: so the rendering cannot drift when a schema field is added.
HEADER_FIELDS = ("type", "parent", "title", "tags", "depth", "verifiable", "visibility")


def render_entry(entry: Entry) -> str:
    """One entry as the model sees it: metadata, then the full body."""
    meta = entry.meta
    lines = [f"### {entry.id}"]

    for field in HEADER_FIELDS:
        value = getattr(meta, field, None)
        if value in (None, "", []):
            continue
        if field == "tags":
            value = ", ".join(value)
        if field == "verifiable":
            value = "yes" if value else "no"
        lines.append(f"{field}: {value}")

    dates = getattr(meta, "dates", None)
    if dates:
        end = dates.end or "present"
        lines.append(f"dates: {dates.start} to {end}")

    org = getattr(meta, "org", None)
    if org:
        lines.append(f"org: {org}")

    if meta.metrics:
        measured = "; ".join(f"{m.value} ({m.what})" for m in meta.metrics)
        lines.append(f"metrics: {measured}")

    if meta.related:
        lines.append(f"related: {', '.join(meta.related)}")

    if meta.locked_phrasing:
        lines.append(f"locked_phrasing: {meta.locked_phrasing}")

    # The body is the part that matters and is never abridged.
    body = entry.body.split("<!--")[0].strip()
    lines.append("")
    lines.append(body or "(no body text yet)")
    return "\n".join(lines)


def render_corpus(corpus: Corpus) -> str:
    """The whole knowledge base, in a stable order, with every body in full."""
    sections: list[str] = [
        "# KNOWLEDGE BASE",
        "",
        "Every entry the candidate has recorded. Entries are grouped by type and",
        "ordered by id. `parent` links a fact to the role or project it sits under.",
        "",
        "Tags are descriptive metadata for human review. They are NOT a filter, and",
        "an entry whose body is relevant must be treated as relevant whether or not",
        "its tags say so.",
        "",
    ]

    for entry in corpus.entries:
        sections.append(render_entry(entry))
        sections.append("")

    if corpus.skills:
        sections.append("### declared skills")
        sections.append("")
        for skill in corpus.skills:
            evidence = ", ".join(skill.evidence)
            sections.append(f"- {skill.skill} ({skill.depth}) — evidence: {evidence}")
        sections.append("")

    return "\n".join(sections)


def render_selected(corpus: Corpus, fact_ids: list[str]) -> str:
    """Only the chosen entries, for the Writer (spec-02 §2).

    Selection and writing have opposite information needs. The Writer gets a
    narrow set on purpose: irrelevant material in context makes bullets blander
    and less targeted, which is the opposite problem from the Selector's.
    """
    by_id = corpus.by_id()
    wanted = [fid for fid in fact_ids if fid in by_id]

    # Parents come too, so the Writer knows the role each fact renders beneath.
    parents: list[str] = []
    for fid in wanted:
        parent = getattr(by_id[fid].meta, "parent", None)
        if parent and parent in by_id and parent not in wanted and parent not in parents:
            parents.append(parent)

    lines = ["# SELECTED CONTENT", ""]
    for entry_id in parents + wanted:
        lines.append(render_entry(by_id[entry_id]))
        lines.append("")
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Rough size, for the context gate. An estimate, labelled as one."""
    return max(1, len(text) // 4)
