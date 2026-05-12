from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import StrEnum
from typing import cast

from codeseam.analysis import (
    AbstractionRisk,
    ActionAssessment,
    ActionKind,
    AssessmentBreakdown,
    AssessmentGate,
    CallsitePattern,
    CandidateGenerationSummary,
    DetectionConfidence,
    EvidenceItem,
    Finding,
    FindingActionStatus,
    FindingDecision,
    FindingLocation,
    FindingMetrics,
    RelationPair,
    SemanticEvidenceMetrics,
)
from codeseam.output.serializers.relations import (
    action_payload,
    context_classification_payload,
    member_ref_payload,
    relation_pair_payload,
)
from codeseam.output.serializers.signatures import (
    callsite_pattern_payload,
    candidate_generation_payload,
    structural_subcluster_payload,
)
from codeseam.platform import Json

FAILED_GATE_DESCRIPTIONS = {
    AssessmentGate.RELATION_DETECTED: ("detection_confidence", "medium_or_high"),
    AssessmentGate.MAINTENANCE_PAYOFF: ("maintenance_payoff", "medium_or_high"),
    AssessmentGate.CLEAN_CLONE_RELATION: ("relation_kind", "body_identical_or_parameterized"),
    AssessmentGate.BODY_HASH_OR_NEAR_IDENTICAL_TREE: (
        "structural_similarity",
        "body_hash_or_tree_ge_0.95",
    ),
    AssessmentGate.LOW_SEMANTIC_RISK: ("semantic_risk", "low"),
    AssessmentGate.LOW_ABSTRACTION_COST: ("abstraction_cost", "low"),
    AssessmentGate.BOUNDED_ABSTRACTION_COST: ("abstraction_cost", "bounded"),
    AssessmentGate.SAME_ROLE_SEMANTICS: ("role_semantics", "same_role"),
    AssessmentGate.SAME_DOWNSTREAM_OPERATION: ("downstream_operation", "shared"),
    AssessmentGate.SMALL_COMMON_BODY: ("common_body", "small"),
    AssessmentGate.LOW_PUBLIC_API_COST: ("public_api_cost", "low"),
    AssessmentGate.STABLE_COMMON_REGION: ("common_region", "stable"),
    AssessmentGate.LOW_HOLE_COUNT: ("hole_count", "low"),
    AssessmentGate.LOW_HOLE_COMPLEXITY: ("hole_complexity", "low"),
    AssessmentGate.LOW_BRANCH_DELTA: ("branch_delta", "low"),
    AssessmentGate.CLEAR_BOUNDARY_OWNER: ("boundary_owner", "clear"),
}
DETECTION_HIGH_ACTUAL = 0.75
DETECTION_MEDIUM_ACTUAL = 0.4


def review_targets_payload(targets: list[Finding], *, precision: int = 4) -> Json:
    return {
        "schema_version": "codeseam.review_targets.v1",
        "targets": [review_target_payload(target, precision=precision) for target in targets],
    }


def review_target_payload(target: Finding, *, precision: int = 4) -> Json:
    payload: Json = {
        "schema_version": "codeseam.review_target.v1",
        "target_id": target.target_id,
        "target_type": target.target_type.value,
        "title": target.title,
        "review_tier": target.review_tier.value,
        "review_score": target.review_score,
        "action_status": target.action_status.value,
        "primary_action": target.primary_action.value,
        "visibility": target.visibility.value,
        "summary_eligible": target.summary_eligible,
        "evidence_strength": target.evidence_strength.value,
        "relatedness_score": target.relatedness_score,
        "refactorability_score": target.refactorability_score,
        "abstraction_cost_score": target.abstraction_cost_score,
        "risk_score": target.risk_score,
        "evidence_classes": list(target.evidence_classes),
        "decision": decision_payload(target.decision),
        "severity": target.severity,
        "confidence": target.confidence,
        "detection_confidence": target.detection_confidence,
        "recommendation_confidence": target.recommendation_confidence,
        "score_model": target.score_model,
        "score_interpretation": target.score_interpretation,
        "assessment": _target_assessment_payload(target, precision),
        "evidence": [evidence_payload(item) for item in target.evidence],
        "reasons": list(target.reasons),
        "non_claims": list(target.non_claims),
        "suggested_refactor_direction": target.suggested_refactor_direction,
        "risk": target.risk,
        "files": list(target.files),
        "locations": [location_payload(location) for location in target.locations],
        "metrics": metrics_payload(target.metrics),
        "overlaps": {key: list(values) for key, values in target.overlaps.items()},
        "lifecycle": target.lifecycle,
        "identity_hash": target.identity_hash,
        "rank": target.rank,
        "rank_label": target.rank_label,
    }
    if semantic_evidence := _semantic_evidence_payload(target.metrics):
        payload["semantic_evidence"] = semantic_evidence
    _add_context_payload(payload, target)
    if target.abstraction_kind:
        payload["abstraction_kind"] = target.abstraction_kind
    if target.abstraction_risks:
        payload["abstraction_risks"] = [
            abstraction_risk_payload(risk) for risk in target.abstraction_risks
        ]
    if target.evidence_kinds:
        payload["evidence_kinds"] = list(target.evidence_kinds)
    if target.callsite_patterns:
        payload["callsite_patterns"] = [
            callsite_pattern_payload(cast(CallsitePattern, pattern))
            for pattern in target.callsite_patterns
        ]
    if target.structural_relation_pairs:
        payload["structural_relation_pairs"] = [
            relation_pair_payload(pair) for pair in target.structural_relation_pairs
        ]
    if target.structural_subclusters:
        payload["structural_subclusters"] = [
            structural_subcluster_payload(subcluster)
            for subcluster in target.structural_subclusters
        ]
    if isinstance(target.candidate_generation, CandidateGenerationSummary):
        payload["candidate_generation"] = candidate_generation_payload(target.candidate_generation)
    if target.refactor_action_candidates:
        payload["refactor_action_candidates"] = [
            action_payload(action) for action in target.refactor_action_candidates
        ]
    if target.refactor_action_summary and target.refactor_action_summary.has_actions:
        payload["refactor_action_summary"] = {
            "primary_action": (
                target.refactor_action_summary.primary_action.value
                if target.refactor_action_summary.primary_action
                else None
            ),
            "secondary_action": (
                target.refactor_action_summary.secondary_action.value
                if target.refactor_action_summary.secondary_action
                else None
            ),
            "not_recommended": [
                action.value for action in target.refactor_action_summary.not_recommended
            ],
            **(
                {"primary_scope": target.refactor_action_summary.primary_scope}
                if target.refactor_action_summary.primary_scope
                else {}
            ),
            **(
                {"secondary_scope": target.refactor_action_summary.secondary_scope}
                if target.refactor_action_summary.secondary_scope
                else {}
            ),
        }
    return payload


def agent_review_target_payload(
    target: Finding,
    *,
    adapter_capabilities: list[Json] | None = None,
) -> Json:
    """Return the public sidecar shape used by agents and CLI summaries.

    Full relation pairs, candidate-generation details, action candidates, and
    scoring audit trails are kept in debug evidence. The default JSONL sidecars
    should be compact enough to scan and cheap enough for tools to stream.
    """

    payload: Json = {
        "schema_version": "codeseam.agent_review_target.v1",
        "target_id": target.target_id,
        "identity_hash": target.identity_hash,
        "target_type": target.target_type.value,
        "title": target.title,
        "review_tier": target.review_tier.value,
        "action_status": target.action_status.value,
        "primary_action": target.primary_action.value,
        "visibility": target.visibility.value,
        "summary_eligible": target.summary_eligible,
        "evidence_strength": target.evidence_strength.value,
        "evidence_classes": list(target.evidence_classes),
        "assessment": _compact_assessment_payload(target),
        "reasons": list(target.reasons),
        "non_claims": list(target.non_claims),
        "files": list(target.files),
        "lifecycle": target.lifecycle,
    }
    _copy_optional_values(
        payload,
        {
            "abstraction_kind": target.abstraction_kind,
            "evidence_kinds": list(target.evidence_kinds),
            "finding_kind": target.finding_kind,
            "context_tags": list(target.context_tags),
            "downgrade_reasons": list(target.downgrade_reasons),
            "refactor_value": target.refactor_value,
            "refactor_safety": target.refactor_safety,
            "summary_reason": target.summary_reason,
            "adapter_capabilities": adapter_capabilities or [],
        },
    )
    if guardrails := _semantic_guardrails(target):
        payload["semantic_guardrails"] = guardrails
    if semantic_evidence := _semantic_evidence(target):
        payload["semantic_evidence"] = semantic_evidence
    pairs = _compact_relation_pairs(target.structural_relation_pairs)
    if pairs:
        payload["structural_relation_pairs"] = pairs
    return payload


def _semantic_guardrails(target: Finding) -> Json:
    role_counts = target.metrics.semantic_role_counts or {}
    roles = sorted(role for role, count in role_counts.items() if count > 0)
    reasons = [*target.metrics.semantic_role_reasons, *target.downgrade_reasons]
    payload: Json = {}
    if roles:
        payload["roles"] = roles
    if reasons:
        payload["reasons"] = list(dict.fromkeys(reasons))
    return payload


def _add_context_payload(payload: Json, target: Finding) -> None:
    if target.finding_kind:
        payload["finding_kind"] = target.finding_kind
    if target.context_tags:
        payload["context_tags"] = list(target.context_tags)
    if target.downgrade_reasons:
        payload["downgrade_reasons"] = list(target.downgrade_reasons)
    if target.refactor_value:
        payload["refactor_value"] = target.refactor_value
    if target.refactor_safety:
        payload["refactor_safety"] = target.refactor_safety
    if target.summary_reason:
        payload["summary_reason"] = target.summary_reason
    if target.context_classifications:
        payload["context_classifications"] = [
            context_classification_payload(classification)
            for classification in target.context_classifications
        ]


def decision_payload(decision: FindingDecision) -> Json:
    return {
        "review_tier": decision.review_tier.value,
        "review_score": decision.review_score,
        "action_status": decision.action_status.value,
        "primary_action": decision.primary_action.value,
        "evidence_strength": decision.evidence_strength.value,
        "relatedness_score": decision.relatedness_score,
        "refactorability_score": decision.refactorability_score,
        "abstraction_cost_score": decision.abstraction_cost_score,
        "risk_score": decision.risk_score,
        "confidence": decision.confidence,
        "evidence_classes": list(decision.evidence_classes),
        "rationale": list(decision.rationale),
    }


def evidence_payload(item: EvidenceItem) -> Json:
    return {"kind": item.kind, **({"id": item.id} if item.id else {})}


def location_payload(location: FindingLocation) -> Json:
    payload: Json = {
        "file": location.file,
        "start_line": location.start_line,
        "end_line": location.end_line,
        "source": location.source,
        "kind": location.kind,
        "symbol": location.symbol,
    }
    if location.message:
        payload["message"] = location.message
    return payload


def metrics_payload(metrics: FindingMetrics) -> Json:
    return _metrics_dataclass_payload(metrics)


def semantic_evidence_metrics_payload(metrics: SemanticEvidenceMetrics) -> Json:
    return _metrics_dataclass_payload(metrics)


type MetricsDataclass = FindingMetrics | SemanticEvidenceMetrics
type MetricValue = (
    str | StrEnum | int | float | tuple[str, ...] | dict[str, int] | Json | None
)


def _metrics_dataclass_payload(metrics: MetricsDataclass) -> Json:
    payload: Json = {}
    for item_field in fields(metrics):
        _add_metric(
            payload,
            item_field.name,
            _metric_payload_value(getattr(metrics, item_field.name)),
        )
    return payload


def _metric_payload_value(value: MetricValue | SemanticEvidenceMetrics) -> MetricValue:
    if isinstance(value, SemanticEvidenceMetrics):
        return semantic_evidence_metrics_payload(value)
    return value


def _add_metric(payload: Json, key: str, value: MetricValue) -> None:
    if value in ("", 0, 0.0, {}, (), [], None):
        return
    if isinstance(value, tuple):
        payload[key] = list(value)
        return
    if isinstance(value, dict):
        compact = {str(item_key): item for item_key, item in value.items() if item != 0}
        if compact:
            payload[key] = compact
        return
    if isinstance(value, StrEnum):
        payload[key] = value.value
        return
    payload[key] = value


def _semantic_evidence_payload(metrics: FindingMetrics) -> Json:
    return semantic_evidence_metrics_payload(metrics.semantic_evidence)


def _semantic_evidence(target: Finding) -> Json:
    return semantic_evidence_metrics_payload(target.metrics.semantic_evidence)


def _compact_assessment_payload(target: Finding) -> Json:
    assessment = target.assessment if isinstance(target.assessment, AssessmentBreakdown) else None
    if assessment is None:
        return {}
    return {
        "detection_confidence": _compact_detection(assessment.detection_confidence),
        "abstraction_fit": _compact_axis(assessment.abstraction_fit),
        "semantic_risk": _compact_axis(assessment.semantic_risk),
        "maintenance_payoff": _compact_axis(assessment.maintenance_payoff),
        "action_recommendation": _compact_action_assessment(
            assessment,
            target,
        ),
    }


def _compact_detection(value: DetectionConfidence) -> Json:
    return {"evidence_quality": value.evidence_quality.value} if value.evidence_quality else {}


def _compact_axis(value: object) -> Json:
    band = getattr(value, "band", None)
    return {"band": band.value} if isinstance(band, StrEnum) else {}


def _compact_action_assessment(
    assessment: AssessmentBreakdown,
    target: Finding,
) -> Json:
    payload: Json = {}
    _copy_action_selection(payload, assessment.action_recommendation, target)
    failed_gates = _failed_gates(assessment.action_recommendation, assessment)
    if failed_gates:
        payload["failed_gates"] = failed_gates
    return payload


def _failed_gates(
    action: ActionAssessment,
    assessment: AssessmentBreakdown,
) -> list[Json]:
    return [_failed_gate(name, assessment) for name in action.preconditions_failed if name]


def _failed_gate(name: AssessmentGate, assessment: AssessmentBreakdown) -> Json:
    gate, required = FAILED_GATE_DESCRIPTIONS.get(name, (name.value, "passed"))
    return {
        "gate": gate,
        "required": required,
        "actual": _gate_actual(gate, assessment),
    }


def _gate_actual(gate: str, assessment: AssessmentBreakdown) -> str:
    if gate == "detection_confidence":
        return _score_actual(assessment.detection_confidence.score)
    if gate == "maintenance_payoff":
        return assessment.maintenance_payoff.band.value
    if gate == "semantic_risk":
        return assessment.semantic_risk.band.value
    if gate == "abstraction_cost":
        return "too_high"
    return "not_satisfied"


def _score_actual(score: float) -> str:
    if score >= DETECTION_HIGH_ACTUAL:
        return "high"
    if score >= DETECTION_MEDIUM_ACTUAL:
        return "medium"
    if score > 0.0:
        return "low"
    return "none"


def _compact_relation_pairs(
    pairs: tuple[RelationPair, ...],
    *,
    limit: int = 3,
) -> list[Json]:
    sorted_pairs = sorted(
        pairs,
        key=lambda pair: (pair.scores.confidence, pair.scores.relatedness),
        reverse=True,
    )
    return [_compact_relation_pair(pair) for pair in sorted_pairs[:limit]]


def _compact_relation_pair(pair: RelationPair) -> Json:
    return {
        "left": member_ref_payload(pair.left),
        "right": member_ref_payload(pair.right),
        "relation_kind": pair.relation_kind.value,
        "relation_kinds": [kind.value for kind in pair.relation_kinds],
        "delta_kinds": [delta.value for delta in pair.delta_kinds],
        "same_role": pair.same_role,
        "role": pair.role,
        "body_hash_match": pair.flags.body_hash_match,
    }


def _copy_optional_values(target: Json, values: Json) -> None:
    for key, value in values.items():
        if value not in (None, "", [], {}, ()):
            target[key] = value


def abstraction_risk_payload(risk: object) -> Json:
    if isinstance(risk, AbstractionRisk):
        payload: Json = {"kind": risk.kind}
        if risk.message:
            payload["message"] = risk.message
        return payload
    return dict(risk) if isinstance(risk, dict) else {"kind": str(risk)}


def _target_assessment_payload(target: Finding, precision: int) -> object:
    payload = _assessment_payload(target.assessment, precision)
    if isinstance(payload, dict):
        _finalize_action_assessment_payload(
            payload,
            primary_action=target.primary_action,
            action_status=target.action_status,
        )
    return payload


def _assessment_payload(value: object, precision: int) -> object:  # noqa: PLR0911
    if isinstance(value, AssessmentBreakdown):
        return {
            "detection_confidence": _assessment_payload(value.detection_confidence, precision),
            "abstraction_fit": _assessment_payload(value.abstraction_fit, precision),
            "semantic_risk": _assessment_payload(value.semantic_risk, precision),
            "maintenance_payoff": _assessment_payload(value.maintenance_payoff, precision),
            "action_recommendation": _assessment_payload(value.action_recommendation, precision),
        }
    if isinstance(value, ActionAssessment):
        return {
            "action_kind": value.action_kind.value,
            "requested_action_kind": (
                value.requested_action_kind.value if value.requested_action_kind else None
            ),
            "status": value.status.value,
            "preconditions_passed": [gate.value for gate in value.preconditions_passed],
            "preconditions_failed": [gate.value for gate in value.preconditions_failed],
            "fallback_reasons": [gate.value for gate in value.fallback_reasons],
            "detection_confidence": _assessment_payload(value.detection_confidence, precision),
            "abstraction_fit": _assessment_payload(value.abstraction_fit, precision),
            "semantic_risk": _assessment_payload(value.semantic_risk, precision),
            "abstraction_cost": _assessment_payload(value.abstraction_cost, precision),
            "recommendation_confidence": _assessment_payload(
                value.recommendation_confidence,
                precision,
            ),
            "recommendation_score": _assessment_payload(value.recommendation_score, precision),
        }
    if is_dataclass(value):
        return {
            field.name: _assessment_payload(getattr(value, field.name), precision)
            for field in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_assessment_payload(item, precision) for item in value]
    if isinstance(value, dict):
        return {str(key): _assessment_payload(item, precision) for key, item in value.items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, float):
        return _clean_score(value, precision)
    return value


def _finalize_action_assessment_payload(
    assessment: Json,
    *,
    primary_action: ActionKind,
    action_status: FindingActionStatus,
) -> None:
    recommendation = assessment.get("action_recommendation")
    if isinstance(recommendation, dict):
        _copy_serialized_action_selection(
            recommendation,
            primary_action=primary_action,
            action_status=action_status,
        )


def _copy_serialized_action_selection(
    payload: Json,
    *,
    primary_action: ActionKind,
    action_status: FindingActionStatus,
) -> None:
    """Finalize full-report action payloads after dataclass serialization."""

    scored_action = _text(payload.get("action_kind"))
    recommendation_status = _text(payload.get("status"))
    requested_action = _text(payload.get("requested_action_kind") or scored_action)
    selected_action = primary_action.value or scored_action
    selected_status = action_status.value or recommendation_status
    if selected_action:
        payload["action_kind"] = selected_action
        payload["selected_action_kind"] = selected_action
    if selected_status:
        payload["status"] = selected_status
        payload["selected_action_status"] = selected_status
    if requested_action:
        payload["requested_action_kind"] = requested_action
    if scored_action:
        payload["scored_action_kind"] = scored_action
    if recommendation_status:
        payload["recommendation_status"] = recommendation_status


def _copy_action_selection(
    payload: Json,
    action: ActionAssessment,
    target: Finding,
) -> None:
    """Copy action fields without hiding semantic-cap rewrites.

    `action_kind` and `status` describe the final selected surface because
    agents consume them as instructions. The raw action scorer result remains
    available under `scored_action_kind` and `recommendation_status`.
    """

    scored_action = action.action_kind.value
    recommendation_status = action.status.value
    requested_action = (
        action.requested_action_kind.value if action.requested_action_kind else scored_action
    )
    selected_action = target.primary_action.value or scored_action
    selected_status = target.action_status.value or recommendation_status
    if selected_action:
        payload["action_kind"] = selected_action
        payload["selected_action_kind"] = selected_action
    if selected_status:
        payload["status"] = selected_status
        payload["selected_action_status"] = selected_status
    if requested_action:
        payload["requested_action_kind"] = requested_action
    if scored_action:
        payload["scored_action_kind"] = scored_action
    if recommendation_status:
        payload["recommendation_status"] = recommendation_status


def _text(value: object) -> str:
    return "" if value in (None, "") else str(value)


def _clean_score(value: float, precision: int) -> float:
    return 0.0 if value == 0 else round(value, precision)


__all__ = [
    "agent_review_target_payload",
    "review_target_payload",
    "review_targets_payload",
]
