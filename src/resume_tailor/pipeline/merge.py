"""Combining the Selector's and Recall's passes (spec-02 §3.3).

**Disagreements are surfaced, not resolved** (AC-R12.2). The union of both
passes goes forward and the review screen marks which facts only one pass
chose. A machine silently arbitrating a recall dispute is exactly the invisible
omission this product exists to prevent — if the two passes disagree, that is
information for the user, not a problem for the merger to tidy away.

So this module has no scoring, no threshold and no tie-break. It is a union
with provenance attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChosenBy = Literal["both", "selector", "recall"]

#: Order for display. Facts both passes agreed on first, then the Selector's
#: alone, then Recall's — so the review screen leads with the strongest
#: consensus and the contested items are visible rather than buried.
_RANK: dict[str, int] = {"both": 0, "selector": 1, "recall": 2}
_STRENGTH: dict[str, int] = {"strong": 0, "moderate": 1, "weak": 2}


@dataclass
class SelectedFact:
    fact_id: str
    chosen_by: ChosenBy
    requirement_ids: list[str] = field(default_factory=list)
    strength: str = "moderate"
    #: The Selector's reason, when it chose this fact.
    reason: str | None = None
    #: Recall's argument, when it nominated this fact.
    argument: str | None = None
    depth: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "chosen_by": self.chosen_by,
            "requirement_ids": self.requirement_ids,
            "strength": self.strength,
            "reason": self.reason,
            "argument": self.argument,
            "depth": self.depth,
        }


@dataclass
class Selection:
    facts: list[SelectedFact] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    tag_proposals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fact_ids(self) -> list[str]:
        return [f.fact_id for f in self.facts]

    @property
    def disputed(self) -> list[SelectedFact]:
        """Facts only one pass chose. The interesting ones."""
        return [f for f in self.facts if f.chosen_by != "both"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self.facts],
            "considered_and_rejected": self.rejected,
            "tag_proposals": self.tag_proposals,
            "counts": {
                "total": len(self.facts),
                "both": sum(1 for f in self.facts if f.chosen_by == "both"),
                "selector_only": sum(1 for f in self.facts if f.chosen_by == "selector"),
                "recall_only": sum(1 for f in self.facts if f.chosen_by == "recall"),
                "rejected": len(self.rejected),
            },
        }


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def merge(
    selection: dict[str, Any],
    recall: dict[str, Any],
    *,
    known_ids: set[str] | None = None,
) -> Selection:
    """Union the two passes, recording which chose what.

    `known_ids` drops hallucinated fact ids. A model occasionally nominates an
    id that does not exist; carrying it forward would make the Writer cite a
    fact nobody can look up, and the Validator would then flag it as a pipeline
    bug — true, but several stages too late to be useful.
    """
    facts: dict[str, SelectedFact] = {}

    for row in _as_list(selection.get("selected")):
        fact_id = row.get("fact_id")
        if not fact_id or (known_ids is not None and fact_id not in known_ids):
            continue
        facts[fact_id] = SelectedFact(
            fact_id=fact_id,
            chosen_by="selector",
            requirement_ids=_as_list(row.get("requirement_ids")),
            strength=row.get("strength") or "moderate",
            reason=row.get("reason"),
            depth=row.get("depth"),
        )

    # Recall's concurrences are agreement, not new nominations: they promote a
    # fact the Selector already chose to "both", and name nothing new.
    for fact_id in _as_list(recall.get("concurrences")):
        if fact_id in facts:
            facts[fact_id].chosen_by = "both"

    for row in _as_list(recall.get("additions")):
        fact_id = row.get("fact_id")
        if not fact_id or (known_ids is not None and fact_id not in known_ids):
            continue
        if fact_id in facts:
            # Both passes reached it independently, which is the strongest
            # signal available here.
            existing = facts[fact_id]
            existing.chosen_by = "both"
            existing.argument = row.get("argument")
            existing.requirement_ids = sorted(
                set(existing.requirement_ids) | set(_as_list(row.get("requirement_ids")))
            )
        else:
            facts[fact_id] = SelectedFact(
                fact_id=fact_id,
                chosen_by="recall",
                requirement_ids=_as_list(row.get("requirement_ids")),
                # A Recall-only nomination is unconfirmed by construction. It
                # still goes forward — surfaced, not resolved — but it is not
                # presented as equal to a fact both passes found.
                strength="weak",
                argument=row.get("argument"),
            )

    # Anything Recall rescued is no longer a rejection, or the review screen
    # would show the same fact as both selected and rejected.
    rescued = set(facts)
    rejected = [
        row
        for row in _as_list(selection.get("considered_and_rejected"))
        if row.get("fact_id") not in rescued
    ]

    ordered = sorted(
        facts.values(),
        key=lambda f: (_RANK[f.chosen_by], _STRENGTH.get(f.strength, 1), f.fact_id),
    )
    return Selection(
        facts=ordered,
        rejected=rejected,
        tag_proposals=_as_list(recall.get("tag_proposals")),
    )


def gap_report(requirements: dict[str, Any], selection: Selection) -> list[dict[str, Any]]:
    """Requirements with no matching fact, or only a weak one (R4).

    The genuinely actionable output: it says what to learn, what to address in
    a cover letter, or which fact is missing from the knowledge base. A
    requirement matched only by a weak or disputed fact is reported as `weak`
    rather than silently counted as covered.
    """
    matched: dict[str, list[SelectedFact]] = {}
    for fact in selection.facts:
        for requirement_id in fact.requirement_ids:
            matched.setdefault(requirement_id, []).append(fact)

    gaps: list[dict[str, Any]] = []
    for requirement in _as_list(requirements.get("requirements")):
        requirement_id = requirement.get("id")
        hits = matched.get(requirement_id, [])
        if not hits:
            status = "absent"
        elif any(f.strength == "strong" for f in hits):
            # Covered. Whether both passes agreed is a separate signal, shown
            # as a badge on the review screen — it says how confident the
            # match is, not whether the requirement was answered.
            continue
        else:
            status = "weak"
        gaps.append(
            {
                "requirement_id": requirement_id,
                "text": requirement.get("text"),
                "kind": requirement.get("kind"),
                "status": status,
                "matched": [f.fact_id for f in hits],
                # Surfaced so a "weak" row says *why* it is weak: one pass
                # found it, or both found it but neither rated it strong.
                "confirmed_by_both": [f.fact_id for f in hits if f.chosen_by == "both"],
            }
        )
    return gaps
