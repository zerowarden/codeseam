from __future__ import annotations

from collections.abc import Sequence

from codeseam.analysis.assessment.action import action_status_for, recommend_action
from codeseam.analysis.assessment.classify import (
    SurfacingAssessment,
    classify_review_tier,
    classify_visibility,
    review_attention_score,
    summary_eligible,
)
from codeseam.analysis.assessment.definitions import EvidenceStrength, FindingReviewVisibility
from codeseam.analysis.assessment.detection import score_detection_confidence
from codeseam.analysis.assessment.evidence import evidence_summary
from codeseam.analysis.assessment.fit import score_abstraction_fit
from codeseam.analysis.assessment.models import (
    AbstractionRisk,
    AssessmentBreakdown,
    ContextClassification,
    ReviewAssessment,
)
from codeseam.analysis.assessment.payoff import score_maintenance_payoff
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.assessment.risk import (
    abstraction_risks_from_values,
    score_semantic_risk,
)
from codeseam.analysis.assessment.semantic_caps import apply_semantic_cap, semantic_cap_for
from codeseam.analysis.findings import (
    Finding,
    FindingDecision,
    FindingDraft,
)
from codeseam.analysis.findings.common import roles_for
from codeseam.analysis.relations.models import (
    ActionKind,
    RefactorAction,
)
from codeseam.caveat_msg import EVIDENCE_CAVEATS

ASSESSMENT_MODEL = "assessment_v2"
ASSESSMENT_INTERPRETATION = "five_axis_review_assessment"
STRONG_EVIDENCE_CLASS_COUNT = 4
MODERATE_EVIDENCE_CLASS_COUNT = 2
RELATION_STRONG_CONFIDENCE = 0.70
RELATION_STRONG_REFACTORABILITY = 0.60
STRONG_DETECTION_CONFIDENCE = 0.85
STRONG_ABSTRACTION_FIT = 0.75
MODERATE_DETECTION_CONFIDENCE = 0.45
CAUTIOUS_SAFETY_THRESHOLD = 0.30
CROSS_LANGUAGE_ACTIONS = {
    ActionKind.OBSERVE,
    ActionKind.RECORD_SHARED_CONCERN,
    ActionKind.INSPECT_SHARED_LIFECYCLE,
    ActionKind.DO_NOT_REFACTOR,
}


def assess_target(
    draft: FindingDraft,
    *,
    roles_by_path: dict[str, str],
    policy: AssessmentPolicy,
) -> Finding:
    roles = roles_for(draft.files, roles_by_path)
    context = _primary_context(draft.context_classifications or ())
    relation_pairs = tuple(draft.structural_relation_pairs or ())
    kinds = tuple(draft.evidence_kinds or ())
    evidence = evidence_summary(
        metrics=draft.metrics,
        evidence_kinds=kinds,
        relation_pairs=relation_pairs,
        has_signature_overlap=draft.has_signature_overlap,
    )
    risks = _effective_risks(
        abstraction_risks_from_values(draft.abstraction_risks),
        relation_strong=draft.metrics.max_relation_confidence_score >= RELATION_STRONG_CONFIDENCE
        and draft.metrics.max_refactorability_score >= RELATION_STRONG_REFACTORABILITY,
    )
    detection = score_detection_confidence(
        draft.metrics,
        evidence=evidence,
        policy=policy.detection,
    )
    fit = score_abstraction_fit(draft.metrics, policy, evidence=evidence)
    semantic_risk = score_semantic_risk(draft.metrics, risks, policy)
    payoff = score_maintenance_payoff(
        draft.metrics,
        roles=roles,
        line_span=draft.line_span,
        distinct_file_count=len(set(draft.files)),
        policy=policy,
    )
    actions = _effective_actions(tuple(draft.refactor_action_candidates or ()), draft, context)
    action = recommend_action(
        actions,
        draft.refactor_action_summary,
        detection=detection,
        fit=fit,
        risk=semantic_risk,
        payoff=payoff,
        metrics=draft.metrics,
        evidence=evidence,
        policy=policy,
    )
    refactor_value = context.refactor_value if context else payoff.band
    surfacing = SurfacingAssessment(
        action,
        detection=detection,
        fit=fit,
        risk=semantic_risk,
        payoff=payoff,
        refactor_value=(
            refactor_value.value if not isinstance(refactor_value, str) else refactor_value
        ),
        policy=policy,
    )
    review_score = review_attention_score(surfacing)
    review_tier = classify_review_tier(surfacing, context=context)
    action_status = action_status_for(action)
    cap = semantic_cap_for(draft.metrics, policy)
    capped = apply_semantic_cap(
        review_tier=review_tier,
        primary_action=action.action_kind,
        action_status=action_status,
        cap=cap,
    )
    review_tier = capped.review_tier
    visibility = classify_visibility(review_tier=review_tier, action=action, context=context)
    eligible = summary_eligible(visibility, context)
    evidence_strength = _evidence_strength(evidence.classes, detection.score, fit.score)
    breakdown = AssessmentBreakdown(
        detection_confidence=detection,
        abstraction_fit=fit,
        semantic_risk=semantic_risk,
        maintenance_payoff=payoff,
        action_recommendation=action,
    )
    assessment = ReviewAssessment(
        review_tier=review_tier,
        review_score=review_score,
        action_status=capped.action_status,
        primary_action=capped.primary_action,
        visibility=visibility,
        summary_eligible=eligible,
        evidence_strength=evidence_strength,
        evidence_classes=evidence.classes,
        breakdown=breakdown,
        rationale=_rationale(detection.score, fit.score, semantic_risk.score, payoff.score),
        summary_reason=_summary_reason(
            visibility,
            capped.primary_action,
            evidence_strength,
            context,
        ),
    )
    decision = _target_decision(assessment)
    return Finding(
        target_type=draft.target_type,
        title=draft.title,
        review_tier=assessment.review_tier,
        review_score=assessment.review_score,
        action_status=assessment.action_status,
        primary_action=assessment.primary_action,
        visibility=assessment.visibility,
        summary_eligible=assessment.summary_eligible,
        evidence_strength=assessment.evidence_strength,
        relatedness_score=detection.score,
        refactorability_score=fit.score,
        abstraction_cost_score=fit.cost,
        risk_score=semantic_risk.score,
        evidence_classes=assessment.evidence_classes,
        decision=decision,
        severity=draft.severity,
        confidence=detection.score,
        detection_confidence=detection.score,
        recommendation_confidence=(
            0.0 if capped.primary_action != action.action_kind else action.recommendation_confidence
        ),
        score_model=ASSESSMENT_MODEL,
        score_interpretation=ASSESSMENT_INTERPRETATION,
        assessment=breakdown,
        evidence=tuple(draft.evidence),
        reasons=tuple(reason for reason in draft.reasons if reason),
        non_claims=tuple(draft.non_claims or EVIDENCE_CAVEATS),
        suggested_refactor_direction=draft.direction,
        risk=draft.risk,
        files=tuple(draft.files),
        locations=tuple(draft.locations),
        metrics=draft.metrics,
        overlaps=draft.overlaps,
        lifecycle={"state": "new", "suppressed": False},
        abstraction_kind=draft.abstraction_kind or "",
        abstraction_risks=tuple(risks),
        evidence_kinds=kinds,
        callsite_patterns=tuple(draft.callsite_patterns or ()),
        structural_relation_pairs=relation_pairs,
        structural_subclusters=tuple(draft.structural_subclusters or ()),
        candidate_generation=draft.candidate_generation,
        refactor_action_candidates=actions,
        refactor_action_summary=draft.refactor_action_summary,
        context_classifications=tuple(draft.context_classifications or ()),
        finding_kind=context.kind if context else "",
        context_tags=context.context_tags if context else (),
        downgrade_reasons=tuple(
            [
                *(context.downgrade_reasons if context else ()),
                *capped.downgrade_reasons,
            ]
        ),
        refactor_value=refactor_value,
        refactor_safety=(
            context.refactor_safety if context else _safety_label(semantic_risk.score, fit.cost)
        ),
        summary_reason=assessment.summary_reason,
    )


def _effective_actions(
    actions: tuple[RefactorAction, ...],
    draft: FindingDraft,
    context: ContextClassification | None,
) -> tuple[RefactorAction, ...]:
    if context is not None and context.action:
        return actions
    if draft.metrics.cluster_scope != "same_language":
        return tuple(action for action in actions if action.kind in CROSS_LANGUAGE_ACTIONS)
    return actions


def _target_decision(assessment: ReviewAssessment) -> FindingDecision:
    return FindingDecision(
        review_tier=assessment.review_tier,
        review_score=assessment.review_score,
        action_status=assessment.action_status,
        primary_action=assessment.primary_action,
        evidence_strength=assessment.evidence_strength,
        relatedness_score=assessment.breakdown.detection_confidence.score,
        refactorability_score=assessment.breakdown.abstraction_fit.score,
        abstraction_cost_score=assessment.breakdown.abstraction_fit.cost,
        risk_score=assessment.breakdown.semantic_risk.score,
        confidence=assessment.breakdown.detection_confidence.score,
        evidence_classes=assessment.evidence_classes,
        rationale=assessment.rationale,
    )


def _effective_risks(
    risks: Sequence[AbstractionRisk],
    *,
    relation_strong: bool,
) -> tuple[AbstractionRisk, ...]:
    if not relation_strong:
        return tuple(risks)
    return tuple(risk for risk in risks if risk.kind != "small_commonality")


def _primary_context(
    classifications: Sequence[object],
) -> ContextClassification | None:
    return next(
        (item for item in classifications if isinstance(item, ContextClassification)),
        None,
    )


def _evidence_strength(
    classes: tuple[str, ...],
    detection_confidence: float,
    abstraction_fit: float,
) -> EvidenceStrength:
    if (
        detection_confidence >= STRONG_DETECTION_CONFIDENCE
        or abstraction_fit >= STRONG_ABSTRACTION_FIT
    ):
        return EvidenceStrength.STRONG
    if len(classes) >= STRONG_EVIDENCE_CLASS_COUNT:
        return EvidenceStrength.STRONG
    if (
        len(classes) >= MODERATE_EVIDENCE_CLASS_COUNT
        or detection_confidence >= MODERATE_DETECTION_CONFIDENCE
    ):
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def _summary_reason(
    visibility: FindingReviewVisibility,
    primary_action: ActionKind,
    evidence_strength: EvidenceStrength,
    context: ContextClassification | None,
) -> str:
    if context and context.downgrade_reasons:
        return context.downgrade_reasons[0]
    if visibility is FindingReviewVisibility.GROUPED:
        return "Grouped because recurrence is visible but action confidence is limited."
    if visibility is FindingReviewVisibility.SIDECAR_ONLY:
        return "Kept in sidecar because one or more assessment axes are weak."
    return (
        f"Listed because {primary_action.value} is supported by {evidence_strength.value} evidence."
    )


def _safety_label(risk: float, cost: float) -> str:
    return "cautious" if max(risk, cost) >= CAUTIOUS_SAFETY_THRESHOLD else "low"


def _rationale(
    detection: float,
    fit: float,
    risk: float,
    payoff: float,
) -> tuple[str, ...]:
    return (
        f"Detection confidence is {detection}.",
        f"Abstraction fit is {fit}.",
        f"Semantic risk is {risk}.",
        f"Maintenance payoff is {payoff}.",
        "Recommendation score is multiplicative, so weak core axes collapse action priority.",
    )


__all__ = ["assess_target"]
