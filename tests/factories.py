from __future__ import annotations

from pathlib import Path

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
    SemanticRisk,
)
from codeseam.cli import render_ci_summary
from codeseam.cli.models import OutputOptions
from codeseam.output.pipeline import ReportArtifacts
from codeseam.output.serializers.analysis import AnalysisPayloadSummary, analysis_result_payload
from codeseam.platform import OutputPaths

REVIEW_CONFIDENCE = 0.26
RECOMMENDATION_CONFIDENCE = 0.7


def ci_summary(targets: list[dict[str, object]]) -> str:
    recommended = sum(
        1 for target in targets if target.get("review_tier") == ReviewTier.RECOMMENDED_EDIT
    )
    review = sum(
        1 for target in targets if target.get("review_tier") == ReviewTier.REVIEW_CANDIDATE
    )
    return render_ci_summary(
        {
            "summary": {
                "files_analysed": 2,
                "files_skipped": 1,
                "functions_seen": 3,
            },
            "findings": {
                ReviewTier.RECOMMENDED_EDIT: recommended,
                ReviewTier.REVIEW_CANDIDATE: review,
                ReviewTier.TRACKING_SIGNAL: 0,
                ReviewTier.OBSERVATION: 0,
            },
            "ci": {
                "fail_on": "recommended_edit",
                "fail_scope": "all_targets",
                "baseline": None,
                "failing_targets": recommended,
                "exit_code": 1 if recommended else 0,
            },
        },
        targets,
    )


def ci_target(
    target_id: str,
    **overrides: object,
) -> dict[str, object]:
    members = overrides.pop("members", None)
    if not isinstance(members, list):
        members = [ci_member("src/target.py", 8, 8, target_id)]
    return {
        "id": target_id,
        "title": target_id,
        "review_tier": ReviewTier.REVIEW_CANDIDATE,
        "confidence": 0.5,
        "review_score": 0.5,
        "primary_action": ActionKind.CONSOLIDATE_CLONE,
        "refactor_value": "medium",
        "refactorability_score": 0.7,
        "visibility": "listed",
        "summary_eligible": True,
        "members": members,
        **overrides,
    }


def ci_member(path: str, start: int, end: int, symbol: str) -> dict[str, object]:
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "symbol": symbol,
    }


def analysis_payload_for_target(tmp_path: Path, target: dict[str, object]) -> dict[str, object]:
    return analysis_result_payload(
        paths=OutputPaths(tmp_path),
        summary=AnalysisPayloadSummary(
            files_analysed=1,
            files_skipped=0,
            functions_seen=1,
        ),
        report_artifacts=ReportArtifacts(
            findings=[],
            analysis_targets=[target],
            observations=[],
            debug_targets=[target],
            report={},
            agent_summary="",
            agent_metrics={"recommended_edit_count": 0},
            meta_readme="",
        ),
        timings={},
    )


def analysis_payload_for_review_target(
    tmp_path: Path,
    *,
    target_id: str = "rt_review",
    title: str = "Similar helper shape",
    overrides: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    target_overrides = dict(overrides or {})
    target_overrides.update(extra)
    target_id = str(target_overrides.pop("target_id", target_id))
    title = str(target_overrides.pop("title", title))
    target = {
        **ci_target(target_id, title=title),
        "target_id": target_id,
        "assessment": {"maintenance_payoff": {"band": "medium"}},
        **target_overrides,
    }
    return analysis_payload_for_target(tmp_path, target)


def output_options(*, color: str = "never") -> OutputOptions:
    return OutputOptions(
        output_format=None,
        output=None,
        quiet=False,
        verbose=False,
        color=color,
        progress="never",
        timings=False,
        target_limit=50,
        ci=False,
    )


def report_artifacts(*, recommended_edit_tier_count: int) -> ReportArtifacts:
    return ReportArtifacts(
        findings=[],
        analysis_targets=[],
        observations=[],
        debug_targets=[],
        report={},
        agent_summary="",
        agent_metrics={"recommended_edit_tier_count": recommended_edit_tier_count},
        meta_readme="",
    )


def agent_payload_fixture(
    *,
    semantic_risk: AssessmentBand,
    failed: tuple[AssessmentGate, ...],
) -> Finding:
    decision = FindingDecision(
        review_tier=ReviewTier.TRACKING_SIGNAL,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.9,
        refactorability_score=0.8,
        abstraction_cost_score=0.7,
        risk_score=0.0,
        confidence=0.6,
        evidence_classes=(),
        rationale=(),
    )
    return Finding(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title="Failed gate fixture",
        review_tier=ReviewTier.TRACKING_SIGNAL,
        review_score=0.0,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        visibility=FindingReviewVisibility.GROUPED,
        summary_eligible=True,
        evidence_strength=EvidenceStrength.STRONG,
        relatedness_score=0.9,
        refactorability_score=0.8,
        abstraction_cost_score=0.7,
        risk_score=0.0,
        evidence_classes=(),
        decision=decision,
        severity="info",
        confidence=0.6,
        detection_confidence=0.6,
        recommendation_confidence=0.4,
        score_model="test",
        score_interpretation="test",
        assessment=AssessmentBreakdown(
            detection_confidence=DetectionConfidence(
                score=0.6,
                evidence_quality=EvidenceQuality.STRUCTURAL,
            ),
            abstraction_fit=AbstractionFit(
                score=0.2,
                band=AssessmentBand.LOW,
                cost=0.7,
            ),
            semantic_risk=SemanticRisk(score=0.7, band=semantic_risk),
            maintenance_payoff=MaintenancePayoff(score=0.4, band=AssessmentBand.LOW),
            action_recommendation=ActionAssessment(
                action_kind=ActionKind.RECORD_SHARED_CONCERN,
                status=RecommendationStatus.CAUTIOUS,
                preconditions_failed=failed,
                detection_confidence=0.6,
                abstraction_fit=0.2,
                semantic_risk=0.7,
                abstraction_cost=0.7,
                recommendation_confidence=0.4,
                recommendation_score=0.0,
            ),
        ),
        evidence=(),
        reasons=(),
        non_claims=(),
        suggested_refactor_direction="",
        risk="",
        files=(),
        locations=(),
        metrics=FindingMetrics(member_count=2),
        overlaps={},
        lifecycle={},
        target_id="rt_failed_gate",
        identity_hash="sha256:target",
    )
