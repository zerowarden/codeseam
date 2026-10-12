from __future__ import annotations

from codeseam.analysis.assessment.definitions import EvidenceQuality, ExtractionConfidence
from codeseam.analysis.assessment.evidence import (
    EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER,
    EVIDENCE_BODY_STRUCTURE_SIMILARITY,
    EVIDENCE_CALL_FINGERPRINT_OVERLAP,
    EVIDENCE_CONTROL_CONTEXT_SIMILARITY,
    EVIDENCE_DUPLICATE_BLOCK,
    EVIDENCE_LOCAL_DATAFLOW_SIMILARITY,
    EVIDENCE_NAME_SIMILARITY,
    EVIDENCE_PARAMETER_USE_SIMILARITY,
    EVIDENCE_SEMANTIC_OVERLOAD_BINDING,
    EVIDENCE_SEMANTIC_SHARED_CALL_TARGET,
)
from codeseam.analysis.assessment.models import (
    DetectionConfidence,
    EvidenceSummary,
)
from codeseam.analysis.assessment.policy import DetectionPolicy
from codeseam.analysis.findings import FindingMetrics

ARGUMENT_NORMALIZATION_SUPPORT = frozenset(
    {
        EVIDENCE_CALL_FINGERPRINT_OVERLAP,
        EVIDENCE_PARAMETER_USE_SIMILARITY,
        EVIDENCE_LOCAL_DATAFLOW_SIMILARITY,
    }
)


def score_detection_confidence(  # noqa: PLR0911
    metrics: FindingMetrics,
    *,
    evidence: EvidenceSummary,
    policy: DetectionPolicy | None = None,
) -> DetectionConfidence:
    """Whether the observed relation is real.

    Detection is intentionally separate from payoff and actionability. Exact
    body/policy evidence can be highly real while still not worth refactoring.
    """
    policy = policy or DetectionPolicy()
    signals: list[str] = []
    if metrics.policy_constant_duplicate_count:
        signals.append("policy_constant_duplicate")
        return _confidence(
            metrics,
            policy.policy_constant_confidence,
            EvidenceQuality.EXACT,
            signals,
            policy,
        )
    if metrics.duplicate_block_count:
        signals.append(EVIDENCE_DUPLICATE_BLOCK)
        score = max(
            policy.structural_duplicate_min_confidence,
            metrics.lead_confidence_score,
        )
        return _confidence(metrics, score, EvidenceQuality.EXACT, signals, policy)
    if metrics.structural_duplicate_pair_count:
        signals.append("structural_duplicate")
        score = max(
            policy.structural_duplicate_min_confidence,
            metrics.lead_confidence_score,
        )
        return _confidence(metrics, score, EvidenceQuality.EXACT, signals, policy)
    if metrics.structural_relation_pair_count:
        signals.append("structural_relation")
        score = _structural_relation_score(
            metrics,
            evidence,
            signals,
            policy,
        )
        return _confidence(metrics, score, EvidenceQuality.STRUCTURAL, signals, policy)
    if evidence.has(EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER):
        signals.append("argument_normalization_wrapper")
        score = _argument_normalization_score(evidence, policy)
        return _confidence(
            metrics,
            score,
            EvidenceQuality.STRUCTURAL,
            signals,
            policy,
        )
    if metrics.member_count >= policy.min_recurrence_members:
        signals.append("signature_shape_recurrence")
        return _confidence(
            metrics,
            policy.signature_only_base_confidence,
            EvidenceQuality.SIGNATURE_ONLY,
            signals,
            policy,
        )
    return DetectionConfidence(0.0, EvidenceQuality.SIGNATURE_ONLY, ())


def _confidence(
    metrics: FindingMetrics,
    score: float,
    quality: EvidenceQuality,
    signals: list[str],
    policy: DetectionPolicy,
) -> DetectionConfidence:
    extraction_confidence = metrics.min_extraction_confidence
    multiplier = _extraction_multiplier(extraction_confidence, policy)
    if multiplier < 1.0:
        signals.append(f"{extraction_confidence.value}_extraction_confidence")
    return DetectionConfidence(round(min(1.0, score * multiplier), 4), quality, tuple(signals))


def _structural_relation_score(
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    signals: list[str],
    policy: DetectionPolicy,
) -> float:
    base = max(
        metrics.lead_confidence_score,
        metrics.lead_relatedness_score * policy.structural_relatedness_multiplier,
    )
    if base == 0.0:
        base = policy.structural_relation_fallback_confidence
    return _boosted(
        base,
        support_count=_structural_support_count(evidence, signals),
        cap=policy.structural_quality_cap,
        policy=policy,
    )


STRUCTURAL_SUPPORT = (
    ("tree_similarity", EVIDENCE_BODY_STRUCTURE_SIMILARITY),
    ("name_similarity", EVIDENCE_NAME_SIMILARITY),
    ("call_fingerprint", EVIDENCE_CALL_FINGERPRINT_OVERLAP),
    ("control_context", EVIDENCE_CONTROL_CONTEXT_SIMILARITY),
    ("semantic_shared_call_target", EVIDENCE_SEMANTIC_SHARED_CALL_TARGET),
    ("semantic_overload_binding", EVIDENCE_SEMANTIC_OVERLOAD_BINDING),
)


def _structural_support_count(evidence: EvidenceSummary, signals: list[str]) -> int:
    """Count corroborating agreement classes; presence of a feature is not support."""

    supported = [signal for signal, item in STRUCTURAL_SUPPORT if evidence.has(item)]
    signals.extend(supported)
    return len(supported)


def _argument_normalization_score(
    evidence: EvidenceSummary,
    policy: DetectionPolicy,
) -> float:
    if any(evidence.has(item) for item in ARGUMENT_NORMALIZATION_SUPPORT):
        return policy.argument_normalization_supported_confidence
    return policy.argument_normalization_base_confidence


def _boosted(
    score: float,
    *,
    support_count: int,
    cap: float,
    policy: DetectionPolicy,
) -> float:
    return min(cap, score + support_count * policy.supporting_signal_boost)


def _extraction_multiplier(value: ExtractionConfidence, policy: DetectionPolicy) -> float:
    return {
        ExtractionConfidence.HIGH: policy.high_extraction_multiplier,
        ExtractionConfidence.MEDIUM: policy.medium_extraction_multiplier,
        ExtractionConfidence.LOW: policy.low_extraction_multiplier,
        ExtractionConfidence.UNKNOWN: policy.unknown_extraction_multiplier,
    }[value]


__all__ = ["score_detection_confidence"]
