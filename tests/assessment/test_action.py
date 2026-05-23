from __future__ import annotations

from pathlib import Path

from codeseam.analysis import (
    AbstractionFit,
    ActionAssessment,
    ActionKind,
    ActionStatus,
    AssessmentBand,
    AssessmentGate,
    AssessmentPolicy,
    DetectionConfidence,
    EvidenceQuality,
    EvidenceSummary,
    FindingActionStatus,
    FindingMetrics,
    MaintenancePayoff,
    MemberRef,
    RecommendationStatus,
    RefactorAction,
    RelationKind,
    SemanticRisk,
    action_status_for,
    recommend_action,
)
from codeseam.config import load_config

POLICY = AssessmentPolicy.from_config(load_config(Path("/repo")).data)
LOW_DETECTION = 0.0
HIGH_DETECTION = 0.95
HIGH_FIT = 0.90
LOW_RISK = 0.05
HIGH_RISK = 0.80
HIGH_PAYOFF = 0.80
LOW_PAYOFF = 0.01
LOW_COST = 0.05
HIGH_CONFIDENCE = 0.90
LARGE_BODY_LINES = 99
LARGE_HOLE_SIZE = 99


def test_recommended_action_status_maps_to_recommended_edit() -> None:
    status = action_status_for(
        ActionAssessment(
            action_kind=ActionKind.CONSOLIDATE_CLONE,
            status=RecommendationStatus.RECOMMENDED,
            preconditions_failed=(),
            detection_confidence=HIGH_DETECTION,
            abstraction_fit=HIGH_FIT,
            semantic_risk=LOW_RISK,
            abstraction_cost=LOW_COST,
            recommendation_confidence=HIGH_CONFIDENCE,
            recommendation_score=HIGH_CONFIDENCE,
        )
    )

    assert status == FindingActionStatus.RECOMMENDED_EDIT


def test_inspect_shared_lifecycle_maps_to_shared_concern_status() -> None:
    status = action_status_for(
        ActionAssessment(
            action_kind=ActionKind.INSPECT_SHARED_LIFECYCLE,
            status=RecommendationStatus.CAUTIOUS,
            preconditions_failed=(),
            detection_confidence=HIGH_DETECTION,
            abstraction_fit=HIGH_FIT,
            semantic_risk=LOW_RISK,
            abstraction_cost=LOW_COST,
            recommendation_confidence=0.0,
            recommendation_score=0.0,
        )
    )

    assert status == FindingActionStatus.RECORD_SHARED_CONCERN


def test_failed_relation_detection_falls_back_to_observe() -> None:
    action = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        detection_score=LOW_DETECTION,
        metrics=_clean_clone_metrics(),
    )

    assert action.action_kind is ActionKind.OBSERVE
    assert action.recommendation_score == 0.0
    assert action.recommendation_confidence == 0.0


def test_payoff_only_failure_keeps_edit_action_for_surfacing() -> None:
    action = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        payoff_score=LOW_PAYOFF,
        metrics=_clean_clone_metrics(),
    )

    assert action.action_kind is ActionKind.CONSOLIDATE_CLONE
    assert action.status is RecommendationStatus.CAUTIOUS
    assert action.preconditions_failed == (AssessmentGate.MAINTENANCE_PAYOFF,)


def test_low_band_clone_risk_does_not_force_safety_stop() -> None:
    action = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        risk_score=0.22,
        metrics=_clean_clone_metrics(),
    )

    assert action.action_kind is ActionKind.CONSOLIDATE_CLONE
    assert AssessmentGate.LOW_SEMANTIC_RISK in action.preconditions_passed


def test_failed_clone_safety_falls_back_to_do_not_refactor() -> None:
    action = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        risk_score=HIGH_RISK,
        metrics=_clean_clone_metrics(),
    )

    assert action.action_kind is ActionKind.DO_NOT_REFACTOR
    assert action.status is RecommendationStatus.NOT_RECOMMENDED


def test_failed_abstraction_introduction_falls_back_to_shared_concern() -> None:
    action = _recommend(
        ActionKind.INTRODUCE_ABSTRACTION,
        metrics=_introduce_abstraction_metrics(max_hole_size=LARGE_HOLE_SIZE),
    )

    assert action.action_kind is ActionKind.RECORD_SHARED_CONCERN
    assert action.recommendation_score == 0.0
    assert action.requested_action_kind is ActionKind.INTRODUCE_ABSTRACTION
    assert AssessmentGate.LOW_HOLE_COMPLEXITY in action.preconditions_failed
    assert action.fallback_reasons == action.preconditions_failed


def test_observe_has_no_edit_recommendation_score() -> None:
    action = _recommend(ActionKind.OBSERVE, metrics=FindingMetrics(member_count=2))

    assert action.action_kind is ActionKind.OBSERVE
    assert action.recommendation_score == 0.0
    assert action.recommendation_confidence == 0.0


def test_relation_note_action_has_no_edit_recommendation_score() -> None:
    action = _recommend(
        ActionKind.INSPECT_SHARED_LIFECYCLE,
        metrics=FindingMetrics(member_count=2, structural_relation_pair_count=1),
    )

    assert action.action_kind is ActionKind.INSPECT_SHARED_LIFECYCLE
    assert action.recommendation_score == 0.0
    assert action.recommendation_confidence == 0.0


def test_missing_helper_body_size_does_not_pass_small_helper_action() -> None:
    action = _recommend(
        ActionKind.EXTRACT_SMALL_HELPER,
        metrics=FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            same_role_relation_count=1,
        ),
        evidence_classes=("argument_normalization_wrapper",),
        preconditions=("shared_operation_after_argument_normalization",),
    )

    assert action.action_kind is ActionKind.RECORD_SHARED_CONCERN


def test_reuse_existing_helper_survives_low_payoff_for_review() -> None:
    action = _recommend(
        ActionKind.REUSE_EXISTING_HELPER,
        metrics=FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            same_role_relation_count=1,
            max_relation_confidence_score=0.72,
        ),
        payoff_score=LOW_PAYOFF,
        risk_score=0.45,
        evidence_classes=("argument_normalization_wrapper",),
        preconditions=(
            "shared_operation_after_argument_normalization",
            "simple_argument_transform",
            "existing_helper_boundary",
        ),
    )

    assert action.action_kind is ActionKind.REUSE_EXISTING_HELPER
    assert action.status is RecommendationStatus.CAUTIOUS
    assert action.preconditions_failed == (AssessmentGate.MAINTENANCE_PAYOFF,)


def test_missing_anti_unification_evidence_blocks_introduce_abstraction() -> None:
    action = _recommend(
        ActionKind.INTRODUCE_ABSTRACTION,
        metrics=_introduce_abstraction_metrics(),
    )

    assert action.action_kind is ActionKind.RECORD_SHARED_CONCERN
    assert AssessmentGate.LOW_HOLE_COUNT in action.preconditions_failed
    assert AssessmentGate.LOW_HOLE_COMPLEXITY in action.preconditions_failed


def test_mixed_role_structural_duplicate_is_not_considered_safe() -> None:
    action = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        metrics=FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            body_hash_match_count=1,
            max_tree_similarity=1.0,
            same_role_relation_count=0,
        ),
    )

    assert action.action_kind is ActionKind.DO_NOT_REFACTOR


def test_recommendation_score_uses_detection_score_not_evidence_quality() -> None:
    structural = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        metrics=_clean_clone_metrics(),
        evidence_quality=EvidenceQuality.STRUCTURAL,
    )
    signature_only = _recommend(
        ActionKind.CONSOLIDATE_CLONE,
        metrics=_clean_clone_metrics(),
        evidence_quality=EvidenceQuality.SIGNATURE_ONLY,
    )

    assert structural.recommendation_score == signature_only.recommendation_score


def _recommend(  # noqa: PLR0913
    kind: ActionKind,
    *,
    metrics: FindingMetrics,
    detection_score: float = HIGH_DETECTION,
    fit_score: float = HIGH_FIT,
    risk_score: float = LOW_RISK,
    payoff_score: float = HIGH_PAYOFF,
    evidence_quality: EvidenceQuality = EvidenceQuality.STRUCTURAL,
    evidence_classes: tuple[str, ...] = (),
    preconditions: tuple[str, ...] = (),
) -> ActionAssessment:
    return recommend_action(
        (_action(kind, preconditions=preconditions),),
        None,
        detection=DetectionConfidence(detection_score, evidence_quality),
        fit=AbstractionFit(fit_score, AssessmentBand.HIGH, LOW_COST),
        risk=SemanticRisk(risk_score, AssessmentBand.LOW),
        payoff=MaintenancePayoff(payoff_score, AssessmentBand.HIGH),
        metrics=metrics,
        evidence=EvidenceSummary.from_classes(evidence_classes),
        policy=POLICY,
    )


def _action(kind: ActionKind, *, preconditions: tuple[str, ...] = ()) -> RefactorAction:
    return RefactorAction(
        kind=kind,
        status=ActionStatus.RECOMMENDED,
        confidence=HIGH_CONFIDENCE,
        applies_to=(_member("left"), _member("right")),
        preconditions=preconditions,
    )


def _member(symbol: str) -> MemberRef:
    return MemberRef(
        signature_id=f"sig_{symbol}",
        function_id=f"fn_{symbol}",
        file=f"src/{symbol}.py",
        symbol=symbol,
        start_line=1,
        end_line=3,
    )


def _clean_clone_metrics() -> FindingMetrics:
    return FindingMetrics(
        member_count=2,
        structural_relation_pair_count=1,
        body_hash_match_count=1,
        max_tree_similarity=1.0,
        relation_kind_counts={RelationKind.BODY_IDENTICAL.value: 1},
        same_role_relation_count=1,
    )


def _introduce_abstraction_metrics(*, max_hole_size: int = 0) -> FindingMetrics:
    return FindingMetrics(
        member_count=2,
        structural_relation_pair_count=1,
        max_stable_statement_count=2,
        max_hole_count=0,
        max_hole_size=max_hole_size,
        same_role_relation_count=1,
    )
