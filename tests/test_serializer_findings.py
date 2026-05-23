from __future__ import annotations

from typing import cast

from codeseam.analysis import (
    AbstractionFit,
    ActionAssessment,
    ActionKind,
    AssessmentBand,
    AssessmentBreakdown,
    AssessmentGate,
    DetectionConfidence,
    EvidenceQuality,
    EvidenceStrength,
    Finding,
    FindingActionStatus,
    FindingDecision,
    FindingMetrics,
    FindingReviewVisibility,
    FindingTargetType,
    MaintenancePayoff,
    RecommendationStatus,
    ReviewTier,
    SemanticEvidenceMetrics,
    SemanticRisk,
)
from codeseam.output.serializers.findings import agent_review_target_payload, metrics_payload


def test_agent_review_target_payload_is_lean_and_explains_failed_gates() -> None:
    payload = agent_review_target_payload(
        _finding(
            target_id="rt_000001",
            title="Duplicate helpers",
            evidence_classes=("body_tree_similarity",),
            reasons=("common code skeleton",),
            non_claims=("not semantic equivalence",),
            files=("src/a.py",),
            lifecycle={"state": "new"},
            assessment=_assessment(
                semantic_risk=AssessmentBand.MEDIUM,
                failed=(AssessmentGate.LOW_SEMANTIC_RISK,),
            ),
        )
    )

    assessment = cast(dict[str, object], payload["assessment"])
    action = cast(dict[str, object], assessment["action_recommendation"])

    assert "metrics" not in payload
    assert "locations" not in payload
    assert assessment["detection_confidence"] == {"evidence_quality": "structural"}
    assert action["action_kind"] == "record_shared_concern"
    assert action["status"] == "record_shared_concern"
    assert action["selected_action_kind"] == "record_shared_concern"
    assert action["selected_action_status"] == "record_shared_concern"
    assert action["scored_action_kind"] == "record_shared_concern"
    assert action["recommendation_status"] == "cautious"
    assert action["failed_gates"] == [
        {"gate": "semantic_risk", "required": "low", "actual": "medium"},
    ]


def test_agent_review_target_payload_serializes_capped_action_as_selected_action() -> None:
    payload = agent_review_target_payload(
        _finding(
            target_id="rt_capped",
            title="Broad parent cluster",
            assessment=_assessment(
                action_kind=ActionKind.CONSOLIDATE_CLONE,
                status=RecommendationStatus.RECOMMENDED,
                requested_action_kind=ActionKind.CONSOLIDATE_CLONE,
            ),
        )
    )

    assessment = cast(dict[str, object], payload["assessment"])
    action = cast(dict[str, object], assessment["action_recommendation"])

    assert action["action_kind"] == "record_shared_concern"
    assert action["status"] == "record_shared_concern"
    assert action["selected_action_kind"] == "record_shared_concern"
    assert action["selected_action_status"] == "record_shared_concern"
    assert action["requested_action_kind"] == "consolidate_clone"
    assert action["scored_action_kind"] == "consolidate_clone"
    assert action["recommendation_status"] == "recommended"


def test_agent_review_target_payload_keeps_lean_semantic_guardrails() -> None:
    payload = agent_review_target_payload(
        _finding(
            target_id="rt_guarded",
            title="Constructor duplicate",
            metrics=FindingMetrics(
                semantic_role_counts={"constructor": 2, "python_special_method": 2},
                semantic_role_reasons=("constructor methods own setup boundaries",),
            ),
            downgrade_reasons=("Semantic role cap: constructors should share setup helpers.",),
        )
    )

    assert "metrics" not in payload
    assert payload["semantic_guardrails"] == {
        "roles": ["constructor", "python_special_method"],
        "reasons": [
            "constructor methods own setup boundaries",
            "Semantic role cap: constructors should share setup helpers.",
        ],
    }


def test_metrics_payload_serializes_semantic_evidence_at_output_boundary() -> None:
    payload = metrics_payload(
        FindingMetrics(
            member_count=2,
            semantic_evidence=SemanticEvidenceMetrics(
                shared_call_target_pair_count=1,
            ),
        )
    )

    assert payload["semantic_evidence"] == {
        "shared_call_target_pair_count": 1,
    }


def test_agent_review_target_payload_keeps_compact_semantic_evidence() -> None:
    payload = agent_review_target_payload(
        _finding(
            target_id="rt_semantic",
            title="Compiler-backed relation",
            metrics=FindingMetrics(
                semantic_evidence=SemanticEvidenceMetrics(shared_call_target_pair_count=1),
            ),
        )
    )

    assert payload["semantic_evidence"] == {
        "shared_call_target_pair_count": 1,
    }


def _assessment(
    *,
    action_kind: ActionKind = ActionKind.RECORD_SHARED_CONCERN,
    status: RecommendationStatus = RecommendationStatus.CAUTIOUS,
    requested_action_kind: ActionKind | None = ActionKind.CONSOLIDATE_CLONE,
    semantic_risk: AssessmentBand = AssessmentBand.LOW,
    failed: tuple[AssessmentGate, ...] = (),
) -> AssessmentBreakdown:
    return AssessmentBreakdown(
        detection_confidence=DetectionConfidence(
            score=0.95,
            evidence_quality=EvidenceQuality.STRUCTURAL,
        ),
        abstraction_fit=AbstractionFit(
            score=0.1,
            band=AssessmentBand.LOW,
            cost=0.2,
        ),
        semantic_risk=SemanticRisk(
            score=0.5,
            band=semantic_risk,
        ),
        maintenance_payoff=MaintenancePayoff(
            score=0.2,
            band=AssessmentBand.LOW,
        ),
        action_recommendation=ActionAssessment(
            action_kind=action_kind,
            requested_action_kind=requested_action_kind,
            status=status,
            preconditions_failed=failed,
            detection_confidence=0.95,
            abstraction_fit=0.1,
            semantic_risk=0.5,
            abstraction_cost=0.2,
            recommendation_confidence=0.0,
            recommendation_score=0.0,
        ),
    )


def _finding(  # noqa: PLR0913
    *,
    target_id: str,
    title: str,
    assessment: AssessmentBreakdown | None = None,
    metrics: FindingMetrics | None = None,
    evidence_classes: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    non_claims: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    lifecycle: object | None = None,
    downgrade_reasons: tuple[str, ...] = (),
) -> Finding:
    decision = FindingDecision(
        review_tier=ReviewTier.MAINTENANCE_NOTE,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.0,
        refactorability_score=0.0,
        abstraction_cost_score=0.0,
        risk_score=0.0,
        confidence=0.0,
        evidence_classes=evidence_classes,
        rationale=(),
    )
    return Finding(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=title,
        review_tier=ReviewTier.MAINTENANCE_NOTE,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        visibility=FindingReviewVisibility.GROUPED,
        summary_eligible=True,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.0,
        refactorability_score=0.0,
        abstraction_cost_score=0.0,
        risk_score=0.0,
        evidence_classes=evidence_classes,
        decision=decision,
        severity="info",
        confidence=0.0,
        detection_confidence=0.0,
        recommendation_confidence=0.0,
        score_model="test",
        score_interpretation="test",
        assessment=assessment or _assessment(),
        evidence=(),
        reasons=reasons,
        non_claims=non_claims,
        suggested_refactor_direction="",
        risk="",
        files=files,
        locations=(),
        metrics=metrics or FindingMetrics(),
        overlaps={},
        lifecycle=lifecycle or {},
        downgrade_reasons=downgrade_reasons,
        target_id=target_id,
        identity_hash="sha256:target",
    )
