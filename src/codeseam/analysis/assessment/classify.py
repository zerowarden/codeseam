from __future__ import annotations

from dataclasses import dataclass

from codeseam.analysis.assessment.bands import assessment_band
from codeseam.analysis.assessment.definitions import (
    AssessmentBand,
    AssessmentGate,
    EvidenceQuality,
    FindingReviewVisibility,
    FindingVisibility,
    RecommendationStatus,
    ReviewTier,
)
from codeseam.analysis.assessment.models import (
    AbstractionFit,
    ActionAssessment,
    ContextClassification,
    DetectionConfidence,
    MaintenancePayoff,
    SemanticRisk,
)
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.relations.models import ActionKind

EDIT_ACTION_KINDS = frozenset(
    (
        ActionKind.CONSOLIDATE_CLONE,
        ActionKind.EXTRACT_SMALL_HELPER,
        ActionKind.INTRODUCE_ABSTRACTION,
        ActionKind.REUSE_EXISTING_HELPER,
    )
)
MAINTENANCE_NOTE_ACTION_KINDS = frozenset(
    (
        ActionKind.RECORD_SHARED_CONCERN,
        ActionKind.INSPECT_SHARED_LIFECYCLE,
    )
)
ATTENTION_BANDS = frozenset((AssessmentBand.MEDIUM, AssessmentBand.HIGH))
LOW_RISK_BANDS = frozenset((AssessmentBand.NONE, AssessmentBand.LOW))
REVIEWABLE_RISK_BANDS = frozenset((AssessmentBand.NONE, AssessmentBand.LOW, AssessmentBand.MEDIUM))
DESIGN_CONCERN_RISK_BANDS = frozenset((AssessmentBand.MEDIUM, AssessmentBand.HIGH))


@dataclass(frozen=True, slots=True)
class SurfacingAssessment:
    """Inputs needed to decide whether a real relation deserves attention."""

    action: ActionAssessment
    detection: DetectionConfidence
    fit: AbstractionFit
    risk: SemanticRisk
    payoff: MaintenancePayoff
    refactor_value: str | AssessmentBand
    policy: AssessmentPolicy


def classify_review_tier(
    assessment: SurfacingAssessment,
    context: ContextClassification | None,
) -> ReviewTier:
    review_score = review_attention_score(assessment)
    if _recommended_edit(assessment):
        tier = ReviewTier.RECOMMENDED_EDIT
    elif _review_candidate(assessment, review_score):
        tier = ReviewTier.REVIEW_CANDIDATE
    elif _maintenance_note(assessment):
        tier = ReviewTier.MAINTENANCE_NOTE
    else:
        tier = ReviewTier.OBSERVATION
    return _apply_context_cap(tier, context)


def review_attention_score(assessment: SurfacingAssessment) -> float:
    """Score whether this finding should consume scarce human review attention.

    Detection confidence answers whether a relation is real. This score answers
    whether that real relation deserves review time. Edit actions reuse their
    gated edit-recommendation score; maintenance-note actions only score when
    they carry a high-value design concern.
    """

    if assessment.action.action_kind in EDIT_ACTION_KINDS:
        if _reuse_existing_helper_preconditions_passed(assessment.action):
            return max(
                assessment.policy.review_candidate_threshold,
                round(max(0.0, assessment.action.recommendation_score), 4),
            )
        return round(max(0.0, assessment.action.recommendation_score), 4)
    if assessment.action.action_kind in MAINTENANCE_NOTE_ACTION_KINDS and _design_concern(
        assessment
    ):
        return _design_concern_attention_score(assessment)
    return 0.0


def _recommended_edit(assessment: SurfacingAssessment) -> bool:
    return (
        assessment.action.action_kind in EDIT_ACTION_KINDS
        and assessment.action.status is RecommendationStatus.RECOMMENDED
        and (
            assessment.action.recommendation_score >= assessment.policy.recommended_edit_threshold
            or _clean_clone_preconditions_passed(assessment.action)
            or _local_duplicate_preconditions_passed(assessment.action)
        )
        and (
            _score_band(assessment.detection.score, assessment.policy) == AssessmentBand.HIGH
            or _clean_clone_preconditions_passed(assessment.action)
        )
        and (
            assessment.payoff.band in ATTENTION_BANDS
            or _clean_clone_preconditions_passed(assessment.action)
        )
        and assessment.fit.band in ATTENTION_BANDS
        and assessment.risk.band in LOW_RISK_BANDS
    )


def _review_candidate(assessment: SurfacingAssessment, review_score: float) -> bool:
    if review_score <= 0.0 or review_score < assessment.policy.review_candidate_threshold:
        return False
    if assessment.action.action_kind in EDIT_ACTION_KINDS:
        if _reuse_existing_helper_preconditions_passed(assessment.action):
            return (
                _score_band(assessment.detection.score, assessment.policy) in ATTENTION_BANDS
                and assessment.risk.band in REVIEWABLE_RISK_BANDS
            )
        return (
            _score_band(assessment.detection.score, assessment.policy) in ATTENTION_BANDS
            and (
                assessment.payoff.band in ATTENTION_BANDS
                or _clean_clone_preconditions_passed(assessment.action)
            )
            and assessment.fit.band in ATTENTION_BANDS
            and assessment.risk.band in REVIEWABLE_RISK_BANDS
            and (
                _refactor_value(assessment.refactor_value) in ATTENTION_BANDS
                or assessment.action.status is RecommendationStatus.RECOMMENDED
            )
        )
    if assessment.action.action_kind in MAINTENANCE_NOTE_ACTION_KINDS:
        return _design_concern(assessment)
    return False


def _maintenance_note(assessment: SurfacingAssessment) -> bool:
    if assessment.action.action_kind in MAINTENANCE_NOTE_ACTION_KINDS:
        return _score_band(assessment.detection.score, assessment.policy) in ATTENTION_BANDS
    if assessment.action.action_kind is ActionKind.DO_NOT_REFACTOR:
        return (
            _score_band(assessment.detection.score, assessment.policy) == AssessmentBand.HIGH
            and assessment.payoff.band in ATTENTION_BANDS
        )
    if assessment.action.action_kind in EDIT_ACTION_KINDS:
        if _local_duplicate_signal(assessment.action):
            return _score_band(assessment.detection.score, assessment.policy) in ATTENTION_BANDS
        return _score_band(
            assessment.detection.score, assessment.policy
        ) in ATTENTION_BANDS and AssessmentBand.LOW in {
            assessment.fit.band,
            assessment.payoff.band,
            _refactor_value(assessment.refactor_value),
        }
    return False


def _local_duplicate_signal(action: ActionAssessment) -> bool:
    return (
        action.action_kind is ActionKind.EXTRACT_SMALL_HELPER
        and AssessmentGate.INTRA_FUNCTION_DUPLICATE_BLOCK in action.preconditions_passed
    )


def classify_visibility(
    *,
    review_tier: ReviewTier,
    action: ActionAssessment,
    context: ContextClassification | None,
) -> FindingReviewVisibility:
    del action
    if review_tier is ReviewTier.OBSERVATION:
        return FindingReviewVisibility.SIDECAR_ONLY
    if context is not None:
        return _review_visibility(context.visibility)
    if review_tier in {ReviewTier.RECOMMENDED_EDIT, ReviewTier.REVIEW_CANDIDATE}:
        return FindingReviewVisibility.LISTED
    if review_tier is ReviewTier.MAINTENANCE_NOTE:
        return FindingReviewVisibility.GROUPED
    return FindingReviewVisibility.SIDECAR_ONLY


def summary_eligible(
    visibility: FindingReviewVisibility,
    context: ContextClassification | None,
) -> bool:
    if context is not None:
        return context.summary_eligible
    return visibility is FindingReviewVisibility.LISTED


def _review_visibility(visibility: FindingVisibility) -> FindingReviewVisibility:
    if visibility is FindingVisibility.AGENT_SUMMARY:
        return FindingReviewVisibility.LISTED
    if visibility is FindingVisibility.SUMMARY_GROUPED:
        return FindingReviewVisibility.GROUPED
    return FindingReviewVisibility.SIDECAR_ONLY


def _score_band(score: float, policy: AssessmentPolicy) -> AssessmentBand:
    return assessment_band(
        score,
        high=policy.high_band_threshold,
        medium=policy.medium_band_threshold,
    )


def _refactor_value(value: str | AssessmentBand) -> AssessmentBand:
    band = _assessment_band(value)
    return band if band in ATTENTION_BANDS | {AssessmentBand.LOW} else AssessmentBand.NONE


def _apply_context_cap(
    tier: ReviewTier,
    context: ContextClassification | None,
) -> ReviewTier:
    if context is None:
        return tier
    if not context.summary_eligible:
        return (
            ReviewTier.MAINTENANCE_NOTE
            if tier in {ReviewTier.RECOMMENDED_EDIT, ReviewTier.REVIEW_CANDIDATE}
            else ReviewTier.OBSERVATION
        )
    if _value(context.refactor_safety) == "unsafe":
        return ReviewTier.OBSERVATION
    if context.action in MAINTENANCE_NOTE_ACTION_KINDS and tier in {
        ReviewTier.RECOMMENDED_EDIT,
        ReviewTier.REVIEW_CANDIDATE,
    }:
        return ReviewTier.MAINTENANCE_NOTE
    if tier is ReviewTier.RECOMMENDED_EDIT and _refactor_value(context.refactor_value) in {
        AssessmentBand.NONE,
        AssessmentBand.LOW,
    }:
        return ReviewTier.REVIEW_CANDIDATE
    return tier


def _design_concern(assessment: SurfacingAssessment) -> bool:
    return (
        assessment.detection.evidence_quality is not EvidenceQuality.SIGNATURE_ONLY
        and assessment.detection.score >= assessment.policy.high_band_threshold
        and assessment.payoff.band == AssessmentBand.HIGH
        and _refactor_value(assessment.refactor_value) in ATTENTION_BANDS
        and (
            assessment.risk.band in DESIGN_CONCERN_RISK_BANDS
            or assessment.action.abstraction_cost >= assessment.policy.cost_block_threshold
        )
    )


def _value_multiplier(value: str) -> float:
    if _refactor_value(value) == AssessmentBand.HIGH:
        return 1.0
    if _refactor_value(value) == AssessmentBand.MEDIUM:
        return 0.7
    return 0.0


def _design_concern_attention_score(assessment: SurfacingAssessment) -> float:
    """Score review attention for risky/costly design recurrences.

    Unlike edit recommendation scoring, higher risk or abstraction cost can
    increase this score because the reason to review is the design concern, not
    immediate edit safety.
    """

    return round(
        assessment.detection.score
        * assessment.payoff.score
        * _value_multiplier(assessment.refactor_value)
        * max(assessment.risk.score, assessment.action.abstraction_cost),
        4,
    )


def _clean_clone_preconditions_passed(action: ActionAssessment) -> bool:
    passed = set(action.preconditions_passed)
    return {
        AssessmentGate.CLEAN_CLONE_RELATION,
        AssessmentGate.BODY_HASH_OR_NEAR_IDENTICAL_TREE,
        AssessmentGate.SAME_ROLE_SEMANTICS,
    } <= passed


def _local_duplicate_preconditions_passed(action: ActionAssessment) -> bool:
    passed = set(action.preconditions_passed)
    return {
        AssessmentGate.INTRA_FUNCTION_DUPLICATE_BLOCK,
        AssessmentGate.SUBSTANTIAL_LOCAL_DUPLICATE_BLOCK,
        AssessmentGate.ARGUMENT_NORMALIZATION_DETECTED,
        AssessmentGate.SAME_DOWNSTREAM_OPERATION,
        AssessmentGate.SMALL_COMMON_BODY,
    } <= passed and action.action_kind is ActionKind.EXTRACT_SMALL_HELPER


def _reuse_existing_helper_preconditions_passed(action: ActionAssessment) -> bool:
    passed = set(action.preconditions_passed)
    return {
        AssessmentGate.ARGUMENT_NORMALIZATION_DETECTED,
        AssessmentGate.SAME_DOWNSTREAM_OPERATION,
        AssessmentGate.SIMPLE_ARGUMENT_TRANSFORM,
        AssessmentGate.EXISTING_HELPER_BOUNDARY,
    } <= passed


def _assessment_band(value: str | AssessmentBand | None) -> AssessmentBand:
    if isinstance(value, AssessmentBand):
        return value
    if value is None:
        return AssessmentBand.NONE
    try:
        return AssessmentBand(value)
    except (TypeError, ValueError):
        return AssessmentBand.NONE


def _value(value: object) -> str:
    item = getattr(value, "value", value)
    return str(item) if item is not None else ""


__all__ = [
    "classify_review_tier",
    "classify_visibility",
    "review_attention_score",
    "summary_eligible",
    "SurfacingAssessment",
]
