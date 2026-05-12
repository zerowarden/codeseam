from __future__ import annotations

from codeseam.analysis.assessment.bands import assessment_band
from codeseam.analysis.assessment.evidence import EVIDENCE_ANTI_UNIFICATION_TEMPLATE
from codeseam.analysis.assessment.metrics import has_relation_pairs
from codeseam.analysis.assessment.models import AbstractionFit, EvidenceSummary
from codeseam.analysis.assessment.policy import AssessmentPolicy, FitPolicy
from codeseam.analysis.assessment.relation_evidence import (
    has_editable_parameterized_skeleton_relation,
)
from codeseam.analysis.findings import FindingMetrics
from codeseam.platform import clamp01, combine_product, inverse_ramp, ramp


def score_abstraction_fit(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    *,
    evidence: EvidenceSummary | None = None,
) -> AbstractionFit:
    """Estimate whether this target has a clean common abstraction.

    The score is not a clone-confidence score. It combines:

    - commonality: how much shared structure exists,
    - simplicity: whether measured variation is small,
    - explicit abstraction cost: public/API or boundary cost from relation scoring,
    - caps: hard limits for weak common regions, high risk, and high cost.

    Semantic risk is mostly handled by `risk.py`; fit uses relation risk only
    as a cap so the assessment axes remain easier to calibrate independently.
    """

    anchors = policy.fit
    evidence = evidence or EvidenceSummary(())
    editable_skeleton = has_editable_parameterized_skeleton_relation(metrics, policy)
    commonality, commonality_reasons = _commonality(metrics, anchors)
    simplicity, simplicity_reasons = _simplicity(
        metrics,
        anchors,
        evidence,
        editable_skeleton=editable_skeleton,
    )
    cost = _explicit_cost(metrics)
    cap, cap_reasons = _fit_cap(metrics, anchors, editable_skeleton=editable_skeleton)
    raw_score = combine_product(
        commonality,
        max(0.15, simplicity),
        max(0.20, 1.0 - cost),
    )
    score = round(clamp01(min(raw_score, cap)), policy.precision)

    return AbstractionFit(
        score,
        assessment_band(
            score,
            high=policy.fit_high_threshold,
            medium=policy.fit_medium_threshold,
        ),
        cost,
        tuple(commonality_reasons + simplicity_reasons + cap_reasons),
    )


def _commonality(metrics: FindingMetrics, anchors: FitPolicy) -> tuple[float, list[str]]:
    """Score shared structure without treating similarity as automatic fit."""

    reasons: list[str] = []
    base = max(
        metrics.max_refactorability_score or 0.0,
        anchors.body_hash_commonality if metrics.body_hash_match_count else 0.0,
        anchors.structural_duplicate_commonality
        if metrics.intra_function_duplicate_block_count
        else 0.0,
        anchors.policy_constant_commonality if metrics.policy_constant_duplicate_count else 0.0,
        anchors.structural_duplicate_commonality
        if metrics.structural_duplicate_pair_count
        else 0.0,
        _structural_relation_commonality(metrics, anchors),
        anchors.signature_only_commonality
        if metrics.member_count >= anchors.recurrence_starts_at_members
        else 0.0,
    )

    if metrics.max_refactorability_score:
        reasons.append("relation_refactorability")
    if metrics.body_hash_match_count:
        reasons.append("body_hash_match")
    if metrics.intra_function_duplicate_block_count:
        reasons.append("intra_function_duplicate")
    if metrics.policy_constant_duplicate_count:
        reasons.append("policy_constant_duplicate")
    if metrics.structural_duplicate_pair_count:
        reasons.append("structural_duplicate")
    elif metrics.structural_relation_pair_count:
        reasons.append("structural_relation")
    elif metrics.member_count >= anchors.recurrence_starts_at_members:
        reasons.append("signature_only_recurrence")
    else:
        reasons.append("no_commonality")

    stable_region = ramp(
        metrics.max_stable_statement_count,
        low=anchors.stable_region_medium_at - 1,
        high=anchors.stable_region_high_at,
    )
    if stable_region:
        reasons.append("stable_common_statement_region")
    if _semantic_commonality_supported(metrics, anchors):
        base = clamp01(base + anchors.semantic_shared_implementation_boost)
        reasons.append("semantic_shared_implementation_evidence")

    if (
        metrics.structural_duplicate_pair_count
        or metrics.body_hash_match_count
        or metrics.intra_function_duplicate_block_count
        or metrics.policy_constant_duplicate_count
    ):
        return clamp01(max(base, stable_region)), reasons
    if has_relation_pairs(metrics):
        return clamp01(base * max(anchors.weak_region_multiplier, stable_region)), reasons
    return clamp01(base), reasons


def _semantic_commonality_supported(metrics: FindingMetrics, anchors: FitPolicy) -> bool:
    """Use provider facts only as corroboration for existing common regions.

    Provider-resolved call targets or overload groups are useful when the
    structural pipeline has already found shared implementation shape. They are
    not standalone fit evidence, because a compiler can prove two calls resolve
    without proving the surrounding bodies should become one abstraction.
    """

    return (
        metrics.semantic_evidence.shared_implementation_pair_count > 0
        and has_relation_pairs(metrics)
        and metrics.max_stable_statement_count >= anchors.stable_region_medium_at
    )


def _structural_relation_commonality(metrics: FindingMetrics, anchors: FitPolicy) -> float:
    if not metrics.structural_relation_pair_count:
        return 0.0
    return max(
        anchors.structural_relation_floor,
        anchors.structural_relation_commonality,
        metrics.max_tree_similarity * anchors.tree_similarity_weight,
        metrics.max_relatedness_score * anchors.relatedness_weight,
    )


def _simplicity(
    metrics: FindingMetrics,
    anchors: FitPolicy,
    evidence: EvidenceSummary,
    *,
    editable_skeleton: bool,
) -> tuple[float, list[str]]:
    """Score whether a shared abstraction would have few and small holes."""

    reasons: list[str] = []
    if editable_skeleton:
        reasons.append("parameterized_skeleton")
        return anchors.parameterized_skeleton_simplicity, reasons
    if not _hole_metrics_available(metrics, evidence) and _holes_matter(metrics):
        reasons.append("hole_metrics_unavailable")
        return anchors.unknown_hole_simplicity, reasons
    hole_count = inverse_ramp(metrics.max_hole_count, low=0, high=anchors.high_hole_count_at)
    hole_size = inverse_ramp(metrics.max_hole_size, low=0, high=anchors.high_hole_size_at)
    if metrics.max_hole_count:
        reasons.append("anti_unification_holes")
    if metrics.max_hole_size:
        reasons.append("large_holes")
    return min(hole_count, hole_size), reasons


def _hole_metrics_available(metrics: FindingMetrics, evidence: EvidenceSummary) -> bool:
    return (
        metrics.max_hole_count > 0
        or metrics.max_hole_size > 0
        or evidence.has(EVIDENCE_ANTI_UNIFICATION_TEMPLATE)
    )


def _holes_matter(metrics: FindingMetrics) -> bool:
    return (
        has_relation_pairs(metrics)
        and not metrics.structural_duplicate_pair_count
        and not metrics.body_hash_match_count
        and not metrics.intra_function_duplicate_block_count
        and not metrics.policy_constant_duplicate_count
    )


def _explicit_cost(metrics: FindingMetrics) -> float:
    return clamp01(metrics.max_abstraction_cost_score or 0.0)


def _fit_cap(
    metrics: FindingMetrics,
    anchors: FitPolicy,
    *,
    editable_skeleton: bool,
) -> tuple[float, list[str]]:
    cap = 1.0
    reasons: list[str] = []

    if metrics.max_abstraction_cost_score >= anchors.high_abstraction_cost_at:
        cap = min(cap, anchors.high_cost_cap)
        reasons.append("high_abstraction_cost_cap")

    if metrics.max_relation_risk_score >= anchors.high_relation_risk_at:
        cap = min(cap, anchors.high_risk_cap)
        reasons.append("high_relation_risk_cap")
    elif metrics.max_relation_risk_score:
        cap = min(cap, max(anchors.high_risk_cap, 1.0 - metrics.max_relation_risk_score))
        reasons.append("relation_risk")

    if (
        metrics.max_stable_statement_count <= 1
        and has_relation_pairs(metrics)
        and not editable_skeleton
        and not metrics.structural_duplicate_pair_count
        and not metrics.body_hash_match_count
        and not metrics.intra_function_duplicate_block_count
        and not metrics.policy_constant_duplicate_count
    ):
        cap = min(cap, anchors.weak_common_region_cap)
        reasons.append("weak_common_region_cap")

    return cap, reasons


__all__ = ["score_abstraction_fit"]
