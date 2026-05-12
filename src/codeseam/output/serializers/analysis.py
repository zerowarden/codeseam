from __future__ import annotations

from dataclasses import dataclass

from codeseam.output.pipeline import ReportArtifacts, threshold_breached
from codeseam.output.serializers.review import target_review_tier, target_review_tier_counts
from codeseam.output.serializers.titles import display_reason, display_shape, display_title
from codeseam.platform import Json, OutputPaths, as_json_objects, text_list

MACHINE_MEMBER_LIMIT = 12


@dataclass(frozen=True, slots=True)
class AnalysisPayloadSummary:
    files_analysed: int
    files_skipped: int
    functions_seen: int
    languages: tuple[str, ...] = ()


def analysis_result_payload(
    *,
    paths: OutputPaths,
    summary: AnalysisPayloadSummary,
    report_artifacts: ReportArtifacts,
    timings: Json,
) -> Json:
    targets = report_artifacts.debug_targets
    review_tier_counts = target_review_tier_counts(targets)
    return {
        "summary": {
            "files_analysed": summary.files_analysed,
            "files_skipped": summary.files_skipped,
            "functions_seen": summary.functions_seen,
            "languages": list(summary.languages),
            "review_targets": len(targets),
        },
        "findings": review_tier_counts,
        "reports": {
            "artifact_root": str(paths.root),
            "human_summary_path": str(paths.artifact("meta_readme")),
            "agent_summary_path": str(paths.artifact("agent_summary")),
            "analysis_path": str(paths.artifact("agent_analysis")),
        },
        "threshold_breached": threshold_breached(report_artifacts),
        "metrics": {
            "recommended_edit_count": report_artifacts.agent_metrics.get(
                "recommended_edit_count",
                0,
            ),
            "analysis_target_count": report_artifacts.agent_metrics.get(
                "analysis_target_count",
                len(report_artifacts.analysis_targets),
            ),
            "observation_count": report_artifacts.agent_metrics.get(
                "observation_count",
                len(report_artifacts.observations),
            ),
        },
        "targets": [_machine_target(target) for target in targets],
        "timings": timings,
    }


def _machine_target(target: Json) -> Json:
    assessment_scores = _assessment_scores(target.get("assessment"))
    members = _member_refs(target)
    return {
        "id": target.get("target_id", ""),
        "title": display_title(target),
        "technical_title": target.get("title", ""),
        "shape": display_shape(target.get("title")),
        "reason": display_reason(target),
        "review_tier": target_review_tier(target),
        "review_score": target.get("review_score", 0.0),
        "action_status": target.get("action_status", ""),
        "primary_action": target.get("primary_action", ""),
        "evidence_strength": target.get("evidence_strength", ""),
        "evidence_classes": text_list(target.get("evidence_classes")),
        # CI and compact summaries use confidence as review/detection confidence:
        # how strongly this target deserves attention. Recommendation confidence
        # is separate: it says how sure we are about the suggested action label,
        # which may still be a weak action such as record_shared_concern.
        "confidence": target.get("detection_confidence", target.get("confidence", 0.0)),
        "recommendation_confidence": target.get("recommendation_confidence", 0.0),
        "assessment_scores": assessment_scores,
        **assessment_scores,
        "refactor_value": target.get("refactor_value", ""),
        "refactorability_score": target.get("refactorability_score", 0.0),
        "visibility": target.get("visibility", ""),
        "summary_eligible": target.get("summary_eligible") is True,
        "summary_reason": target.get("summary_reason", ""),
        "lifecycle": target.get("lifecycle", {}),
        "member_count": len(members),
        "member_limit": MACHINE_MEMBER_LIMIT,
        "members_truncated": len(members) > MACHINE_MEMBER_LIMIT,
        "members": members[:MACHINE_MEMBER_LIMIT],
    }


def _assessment_scores(assessment: object) -> Json:
    if not isinstance(assessment, dict):
        return {}
    recommendation = assessment.get("action_recommendation", {})
    action_score = (
        recommendation.get("recommendation_score", 0.0) if isinstance(recommendation, dict) else 0.0
    )
    recommendation_confidence = (
        recommendation.get("recommendation_confidence", 0.0)
        if isinstance(recommendation, dict)
        else 0.0
    )
    abstraction_cost = (
        recommendation.get("abstraction_cost", 0.0) if isinstance(recommendation, dict) else 0.0
    )
    return {
        "detection_confidence": _score(assessment.get("detection_confidence")),
        "abstraction_fit": _score(assessment.get("abstraction_fit")),
        "semantic_risk": _score(assessment.get("semantic_risk")),
        "maintenance_payoff": _score(assessment.get("maintenance_payoff")),
        "assessment_bands": {
            "detection_confidence": _band(assessment.get("detection_confidence")),
            "abstraction_fit": _band(assessment.get("abstraction_fit")),
            "semantic_risk": _band(assessment.get("semantic_risk")),
            "maintenance_payoff": _band(assessment.get("maintenance_payoff")),
        },
        "action_recommendation": {
            "score": action_score,
            "confidence": recommendation_confidence,
            "abstraction_cost": abstraction_cost,
            "status": recommendation.get("status", "") if isinstance(recommendation, dict) else "",
            "action": (
                recommendation.get("action_kind", "") if isinstance(recommendation, dict) else ""
            ),
        },
        "abstraction_cost": abstraction_cost,
        "action_score": action_score,
    }


def _score(value: object) -> object:
    if isinstance(value, dict):
        return value.get("score", 0.0)
    return 0.0


def _band(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("band") or "")
    return ""


def _member_refs(target: Json) -> list[Json]:
    pair_refs = _relation_pair_member_refs(target)
    if pair_refs:
        return pair_refs
    return [_member_ref(location) for location in as_json_objects(target.get("locations"))]


def _relation_pair_member_refs(target: Json) -> list[Json]:
    refs: list[Json] = []
    for pair in as_json_objects(target.get("structural_relation_pairs")):
        refs.extend(
            _member_ref(member)
            for member in (pair.get("left"), pair.get("right"))
            if isinstance(member, dict)
        )
    return list({str(ref): ref for ref in refs if ref.get("path")}.values())


def _member_ref(member: Json) -> Json:
    return {
        "path": member.get("file", ""),
        "start_line": member.get("start_line", 0),
        "end_line": member.get("end_line", 0),
        "symbol": member.get("symbol", ""),
    }
