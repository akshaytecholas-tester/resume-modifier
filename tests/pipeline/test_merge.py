"""Merging the two selection passes (spec-02 §3.3, AC-R12.2).

The invariant under test: **disagreements are surfaced, not resolved.** A
machine silently arbitrating a recall dispute is the invisible omission this
product exists to prevent, so there is no scoring, threshold or tie-break to
test — only that both passes' output survives with its provenance attached.
"""

from __future__ import annotations

from resume_tailor.pipeline.merge import gap_report, merge

SELECTION = {
    "selected": [
        {"fact_id": "a", "requirement_ids": ["RQ1"], "strength": "strong", "reason": "direct hit"},
        {"fact_id": "b", "requirement_ids": ["RQ2"], "strength": "weak", "reason": "maybe"},
    ],
    "considered_and_rejected": [
        {"fact_id": "c", "reason": "unrelated"},
        {"fact_id": "d", "reason": "also unrelated"},
    ],
}

RECALL = {
    "additions": [{"fact_id": "d", "requirement_ids": ["RQ3"], "argument": "tagging gap"}],
    "tag_proposals": [{"fact_id": "d", "add_tags": ["x"], "why": "body says x"}],
    "concurrences": ["a"],
}

KNOWN = {"a", "b", "c", "d"}


def test_the_union_of_both_passes_goes_forward() -> None:
    result = merge(SELECTION, RECALL, known_ids=KNOWN)
    assert set(result.fact_ids) == {"a", "b", "d"}


def test_provenance_is_recorded_per_fact() -> None:
    by_id = {f.fact_id: f for f in merge(SELECTION, RECALL, known_ids=KNOWN).facts}
    assert by_id["a"].chosen_by == "both"  # selector chose it, recall concurred
    assert by_id["b"].chosen_by == "selector"  # selector only
    assert by_id["d"].chosen_by == "recall"  # recall rescued it


def test_disputed_facts_are_identifiable() -> None:
    """The review screen badges these; it is the whole point of two passes."""
    disputed = {f.fact_id for f in merge(SELECTION, RECALL, known_ids=KNOWN).disputed}
    assert disputed == {"b", "d"}


def test_a_rescued_fact_leaves_the_rejected_list() -> None:
    """Otherwise the same fact shows as both selected and rejected."""
    result = merge(SELECTION, RECALL, known_ids=KNOWN)
    assert [r["fact_id"] for r in result.rejected] == ["c"]


def test_recall_only_facts_are_marked_weak() -> None:
    """Unconfirmed by construction: one pass found it. It still goes forward —
    surfaced, not resolved — but is not presented as equal to a consensus pick."""
    by_id = {f.fact_id: f for f in merge(SELECTION, RECALL, known_ids=KNOWN).facts}
    assert by_id["d"].strength == "weak"


def test_both_passes_finding_a_fact_independently_is_recorded() -> None:
    recall = {"additions": [{"fact_id": "a", "requirement_ids": ["RQ9"], "argument": "also this"}]}
    by_id = {f.fact_id: f for f in merge(SELECTION, recall, known_ids=KNOWN).facts}
    assert by_id["a"].chosen_by == "both"
    assert by_id["a"].reason and by_id["a"].argument  # both rationales kept
    assert set(by_id["a"].requirement_ids) == {"RQ1", "RQ9"}


def test_hallucinated_ids_are_dropped() -> None:
    """A model occasionally nominates an id that does not exist. Carrying it
    makes the Writer cite a fact nobody can look up."""
    recall = {"additions": [{"fact_id": "ghost", "argument": "invented"}]}
    assert "ghost" not in merge(SELECTION, recall, known_ids=KNOWN).fact_ids


def test_without_known_ids_nothing_is_dropped() -> None:
    recall = {"additions": [{"fact_id": "ghost", "argument": "invented"}]}
    assert "ghost" in merge(SELECTION, recall).fact_ids


def test_ordering_leads_with_consensus() -> None:
    order = [f.chosen_by for f in merge(SELECTION, RECALL, known_ids=KNOWN).facts]
    assert order == sorted(order, key=["both", "selector", "recall"].index)


def test_counts_are_reported() -> None:
    counts = merge(SELECTION, RECALL, known_ids=KNOWN).to_dict()["counts"]
    assert counts == {"total": 3, "both": 1, "selector_only": 1, "recall_only": 1, "rejected": 1}


def test_empty_recall_is_a_valid_answer() -> None:
    """ "The first pass missed nothing" is useful output, not a failure."""
    result = merge(SELECTION, {"additions": [], "concurrences": []}, known_ids=KNOWN)
    assert len(result.facts) == 2
    assert all(f.chosen_by == "selector" for f in result.facts)


def test_malformed_agent_output_does_not_crash_the_merge() -> None:
    assert merge({}, {}).facts == []
    assert merge({"selected": None}, {"additions": "nonsense"}).facts == []


# -- gap report ------------------------------------------------------------

REQUIREMENTS = {
    "requirements": [
        {"id": "RQ1", "text": "Strongly matched", "kind": "required"},
        {"id": "RQ2", "text": "Weakly matched", "kind": "required"},
        {"id": "RQ3", "text": "Recall rescued", "kind": "preferred"},
        {"id": "RQ4", "text": "Nothing at all", "kind": "required"},
    ]
}


def test_unmatched_requirements_are_absent() -> None:
    gaps = gap_report(REQUIREMENTS, merge(SELECTION, RECALL, known_ids=KNOWN))
    absent = {g["requirement_id"] for g in gaps if g["status"] == "absent"}
    assert absent == {"RQ4"}


def test_weakly_matched_requirements_are_not_counted_as_covered() -> None:
    """Silently counting a weak match as covered is how a gap disappears."""
    gaps = {
        g["requirement_id"]: g
        for g in gap_report(REQUIREMENTS, merge(SELECTION, RECALL, known_ids=KNOWN))
    }
    assert gaps["RQ2"]["status"] == "weak"
    assert gaps["RQ3"]["status"] == "weak"


def test_strongly_matched_requirements_are_not_gaps() -> None:
    gaps = {
        g["requirement_id"]
        for g in gap_report(REQUIREMENTS, merge(SELECTION, RECALL, known_ids=KNOWN))
    }
    assert "RQ1" not in gaps


def test_a_weak_gap_says_what_matched_it() -> None:
    gaps = {
        g["requirement_id"]: g
        for g in gap_report(REQUIREMENTS, merge(SELECTION, RECALL, known_ids=KNOWN))
    }
    assert gaps["RQ2"]["matched"] == ["b"]
