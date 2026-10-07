"""The gap report (R4) — the genuinely actionable output of a run.

A tailored resume tells you what you can say. The gap report tells you what you
cannot, which is the part that changes what you do next: what to learn, what to
address in a cover letter, or which fact is missing from the knowledge base.
"""

from __future__ import annotations

from typing import Any

from .merge import Selection


def render_gap_report(
    requirements: dict[str, Any],
    selection: Selection,
    gaps: list[dict[str, Any]],
    validation: dict[str, Any] | None = None,
) -> str:
    title = requirements.get("role_title") or "this posting"
    lines = [f"# Gap report — {title}", ""]

    absent = [g for g in gaps if g["status"] == "absent"]
    weak = [g for g in gaps if g["status"] == "weak"]
    total = len(requirements.get("requirements") or [])
    lines += [
        f"{total - len(gaps)} of {total} requirements covered. "
        f"{len(absent)} absent, {len(weak)} weak.",
        "",
    ]

    if absent:
        lines += ["## Nothing in the knowledge base answers these", ""]
        for gap in absent:
            lines.append(f"- **{gap['text']}** ({gap['kind']})")
        lines += [
            "",
            "Each is either a real gap worth addressing in a cover letter, or a fact "
            "you have not written down yet. The second is far more common than it feels.",
            "",
        ]

    if weak:
        lines += ["## Matched, but not strongly", ""]
        for gap in weak:
            matched = ", ".join(gap["matched"]) or "nothing"
            lines.append(f"- **{gap['text']}** — matched by {matched}")
        lines += [
            "",
            "Usually means the fact is real but its body is too thin to carry the claim. "
            "Expanding it in the knowledge base is the fix.",
            "",
        ]

    disputed = selection.disputed
    if disputed:
        lines += ["## Where the two passes disagreed", ""]
        for fact in disputed:
            why = fact.argument or fact.reason or ""
            lines.append(f"- `{fact.fact_id}` — **{fact.chosen_by} only**. {why}")
        lines += [
            "",
            "Surfaced rather than resolved. A fact only the recall pass found is often "
            "the one with a tagging gap; one only the first pass found may be a stretch.",
            "",
        ]

    if selection.tag_proposals:
        lines += ["## Suggested tags", ""]
        for proposal in selection.tag_proposals:
            tags = ", ".join(proposal.get("add_tags") or [])
            lines.append(f"- `{proposal.get('fact_id')}`: add {tags} — {proposal.get('why', '')}")
        lines.append("")

    if validation:
        cuts = validation.get("cuts") or []
        warnings = validation.get("warnings") or []
        if cuts or warnings:
            lines += ["## Validator", ""]
            for cut in cuts:
                lines.append(f"- **cut**: {cut.get('reason')}")
            for warning in warnings:
                lines.append(f"- **{warning.get('kind', 'warning')}**: {warning.get('reason')}")
            lines += [
                "",
                "A cut claim usually means a real fact is missing from the knowledge base "
                "rather than that the writer invented something.",
                "",
            ]

    if len(lines) <= 4:
        lines.append("No gaps found. Every requirement is matched by a strong fact.")

    return "\n".join(lines).rstrip() + "\n"
