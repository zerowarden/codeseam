from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from codeseam.analysis.assessment.definitions import AssessmentBand
from codeseam.analysis.assessment.models import AbstractionRisk, SemanticRisk
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.findings import FindingMetrics


def score_semantic_risk(
    metrics: FindingMetrics,
    risks: Sequence[AbstractionRisk],
    policy: AssessmentPolicy,
) -> SemanticRisk:
    """Answer whether merging could change meaning or create a bad abstraction."""
    score = metrics.max_relation_risk_score
    semantic_score, semantic_reasons = _semantic_evidence_risk(metrics, policy)
    if not score:
        risk_units = len(risks)
        if metrics.cluster_scope != "same_language":
            risk_units += 1
        score = min(1.0, risk_units * 0.12)
    score = max(score, semantic_score)
    reasons = tuple(risk.kind for risk in risks if risk.kind) + semantic_reasons
    return SemanticRisk(round(min(1.0, score), 4), _risk_band(score, policy), reasons)


def abstraction_risks_from_values(values: Iterable[object] | None) -> tuple[AbstractionRisk, ...]:
    risks: list[AbstractionRisk] = []
    for value in values or ():
        risk = abstraction_risk_from_value(value)
        if risk:
            risks.append(risk)
    return tuple(risks)


def abstraction_risk_from_value(value: object) -> AbstractionRisk | None:
    if isinstance(value, AbstractionRisk):
        return value
    if not isinstance(value, Mapping):
        return None
    kind = str(value.get("kind", ""))
    if not kind:
        return None
    return AbstractionRisk(kind=kind, message=str(value.get("message", "")))


def _risk_band(score: float, policy: AssessmentPolicy) -> AssessmentBand:
    if score >= policy.risk_block_threshold:
        return AssessmentBand.HIGH
    if score >= policy.risk_cautious_threshold:
        return AssessmentBand.MEDIUM
    if score > 0:
        return AssessmentBand.LOW
    return AssessmentBand.NONE


def _semantic_evidence_risk(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> tuple[float, tuple[str, ...]]:
    """Convert optional semantic-provider uncertainty into generic caution.

    This function deliberately does not know which language produced the
    provider facts. Declaration-only spans, unresolved ownership, and divergent
    resolved call targets are all risks to refactoring regardless of whether the
    provider was TypeScript, Rust, Swift, or another implementation.
    """

    semantic = metrics.semantic_evidence
    score = 0.0
    reasons: list[str] = []
    if semantic.declaration_only_count:
        score += policy.semantic_evidence.declaration_surface_risk_unit
        reasons.append("semantic_declaration_surface")
    if semantic.unresolved_item_count:
        score += policy.semantic_evidence.unresolved_semantics_risk_unit
        reasons.append("semantic_unresolved")
    if semantic.ambiguous_ownership_count:
        score += policy.semantic_evidence.ambiguous_ownership_risk_unit
        reasons.append("semantic_ambiguous_ownership")
    if semantic.divergent_call_target_pair_count:
        score = max(score, policy.semantic_evidence.divergent_call_target_risk_floor)
        reasons.append("semantic_divergent_call_target")
    return min(1.0, score), tuple(reasons)


__all__ = [
    "abstraction_risk_from_value",
    "abstraction_risks_from_values",
    "score_semantic_risk",
]
