"""Report surfaces are decided on typed findings before anything is serialized."""

from __future__ import annotations

from dataclasses import replace

import pytest
from factories import agent_payload_fixture

from codeseam.analysis import (
    ActionKind,
    AssessmentBand,
    Finding,
    FindingActionStatus,
    FindingReviewVisibility,
    ReviewTier,
    surface_findings,
)
from codeseam.analysis.assessment.classify import SummaryInputs, summary_eligible


def _finding(target_id: str, tier: ReviewTier, *, eligible: bool = False) -> Finding:
    finding = agent_payload_fixture(semantic_risk=AssessmentBand.LOW, failed=())
    return replace(finding, target_id=target_id, review_tier=tier, summary_eligible=eligible)


@pytest.mark.parametrize(
    ("tier", "in_analysis"),
    [
        (ReviewTier.RECOMMENDED_EDIT, True),
        (ReviewTier.REVIEW_CANDIDATE, True),
        (ReviewTier.MAINTENANCE_NOTE, True),
        (ReviewTier.OBSERVATION, False),
    ],
)
def test_analysis_sidecar_follows_the_final_tier(tier: ReviewTier, in_analysis: bool) -> None:
    surfaced = surface_findings([_finding("rt_a", tier)])

    assert (len(surfaced.analysis), len(surfaced.observations)) == (
        (1, 0) if in_analysis else (0, 1)
    )


def test_surfaces_keep_rank_order_and_the_first_finding_per_id() -> None:
    first = _finding("rt_same", ReviewTier.RECOMMENDED_EDIT, eligible=True)
    surfaced = surface_findings(
        [
            first,
            _finding("rt_other", ReviewTier.OBSERVATION),
            _finding("rt_same", ReviewTier.MAINTENANCE_NOTE),
        ]
    )

    assert [item.target_id for item in surfaced.ranked] == ["rt_same", "rt_other"]
    assert surfaced.agent_summary == (first,)
    assert surfaced.recommended_edit_tier_count == 1


def test_recommended_edit_count_reads_summary_targets_only() -> None:
    edit = replace(
        _finding("rt_edit", ReviewTier.RECOMMENDED_EDIT, eligible=True),
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
    )
    unlisted = replace(edit, target_id="rt_unlisted", summary_eligible=False)

    surfaced = surface_findings([edit, unlisted])

    assert surfaced.recommended_edit_count == 1
    assert surfaced.recommended_edit_tier_count == 2  # noqa: PLR2004


LISTED = SummaryInputs(
    review_tier=ReviewTier.REVIEW_CANDIDATE,
    visibility=FindingReviewVisibility.LISTED,
    payoff_band=AssessmentBand.MEDIUM,
    refactorability=0.8,
    action_status=FindingActionStatus.CAUTIOUS_CANDIDATE,
    primary_action=ActionKind.CONSOLIDATE_CLONE,
)


@pytest.mark.parametrize(
    ("change", "eligible"),
    [
        ({}, True),
        ({"visibility": FindingReviewVisibility.SIDECAR_ONLY}, False),
        ({"payoff_band": AssessmentBand.LOW}, False),
        ({"refactorability": 0.2}, False),
        ({"action_status": FindingActionStatus.RECORD_SHARED_CONCERN}, False),
        ({"primary_action": ActionKind.OBSERVE}, False),
        ({"review_tier": ReviewTier.RECOMMENDED_EDIT, "payoff_band": AssessmentBand.LOW}, True),
    ],
    ids=[
        "listed-edit",
        "not-listed",
        "low-payoff",
        "low-refactorability",
        "note-status",
        "note-action",
        "recommended-always",
    ],
)
def test_summary_eligibility_is_decided_on_the_assessment(
    change: dict[str, object], eligible: bool
) -> None:
    assert summary_eligible(replace(LISTED, **change)) is eligible  # type: ignore[arg-type]
