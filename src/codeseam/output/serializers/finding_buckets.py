from __future__ import annotations

from codeseam.analysis import (
    RELATION_ASSESSMENT_POLICY,
    ActionKind,
    FindingActionStatus,
    FindingReviewVisibility,
    FindingVisibility,
    ReviewTier,
    ScoreBand,
)
from codeseam.platform import Json, json_float

ANALYSIS_REVIEW_TIERS: frozenset[str] = frozenset(
    {
        ReviewTier.RECOMMENDED_EDIT.value,
        ReviewTier.REVIEW_CANDIDATE.value,
        ReviewTier.TRACKING_SIGNAL.value,
    }
)


def is_analysis_target(target: Json) -> bool:
    """Return whether a target belongs in the compact analysis sidecar.

    The sidecar boundary follows the final surfacing decision, not raw action
    candidates. A target may have a plausible candidate action and still be an
    observation after semantic caps, context caps, or safety gates.
    """

    lifecycle = target.get("lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("suppressed") is True:
        return False

    return _text(target.get("review_tier", ReviewTier.OBSERVATION.value)) in ANALYSIS_REVIEW_TIERS


def canonical_analysis_targets(targets: list[Json]) -> list[Json]:
    seen: set[str] = set()
    canonical: list[Json] = []
    for target in targets:
        target_id = str(target.get("target_id", ""))
        if not target_id:
            canonical.append(target)
            continue
        if target_id in seen:
            continue
        seen.add(target_id)
        canonical.append(target)
    return canonical


def partition_analysis_targets(
    targets: list[Json],
) -> tuple[list[Json], list[Json]]:
    analysis: list[Json] = []
    observations: list[Json] = []
    for target in targets:
        bucket = analysis if is_analysis_target(target) else observations
        bucket.append(target)
    return analysis, observations


def agent_summary_targets(targets: list[Json]) -> list[Json]:
    return [
        target
        for target in partition_analysis_targets(targets)[0]
        if is_agent_summary_target(target)
    ]


def is_agent_summary_target(target: Json) -> bool:
    return (
        target.get("summary_eligible") is True
        and is_review_surface_target(target)
        and _text(target.get("visibility"))
        in {FindingReviewVisibility.LISTED.value, FindingVisibility.AGENT_SUMMARY.value}
    )


def is_review_surface_target(target: Json) -> bool:
    if _text(target.get("review_tier")) == ReviewTier.RECOMMENDED_EDIT.value:
        return True
    if _is_low_refactor_value(target.get("refactor_value")):
        return False
    if _low_refactorability(target):
        return False
    return not _is_tracking_action(target)


def _low_refactorability(target: Json) -> bool:
    return (
        json_float(
            target.get("refactorability_score"),
            RELATION_ASSESSMENT_POLICY.refactorability_medium_threshold,
        )
        < RELATION_ASSESSMENT_POLICY.refactorability_medium_threshold
    )


def _is_tracking_action(target: Json) -> bool:
    return _text(target.get("action_status")) in {
        FindingActionStatus.RECORD_SHARED_CONCERN.value,
        FindingActionStatus.OBSERVE.value,
        FindingActionStatus.DO_NOT_REFACTOR.value,
    } or _text(target.get("primary_action")) in {
        ActionKind.RECORD_SHARED_CONCERN.value,
        ActionKind.OBSERVE.value,
        ActionKind.DO_NOT_REFACTOR.value,
    }


def _is_low_refactor_value(value: object) -> bool:
    return _text(value) in {ScoreBand.LOW.value, ScoreBand.TRACK_ONLY.value, "none"}


def _text(value: object) -> str:
    return "" if value is None else str(value)
