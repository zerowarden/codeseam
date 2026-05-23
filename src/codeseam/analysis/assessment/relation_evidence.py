from __future__ import annotations

from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.findings import FindingMetrics
from codeseam.analysis.relations import (
    CLEAN_CLONE_RELATIONS,
    PARAMETERIZED_SKELETON_RELATIONS,
    RelationKind,
)


def relation_count(metrics: FindingMetrics, relation_kind: RelationKind) -> int:
    return (metrics.relation_kind_counts or {}).get(relation_kind.value, 0)


def has_relation_kind(
    metrics: FindingMetrics,
    relation_kinds: frozenset[RelationKind],
) -> bool:
    return any(relation_count(metrics, relation_kind) > 0 for relation_kind in relation_kinds)


def has_exact_clone_relation(metrics: FindingMetrics) -> bool:
    return metrics.structural_duplicate_pair_count > 0 or has_relation_kind(
        metrics,
        CLEAN_CLONE_RELATIONS,
    )


def has_parameterized_skeleton_relation(metrics: FindingMetrics) -> bool:
    return has_relation_kind(metrics, PARAMETERIZED_SKELETON_RELATIONS)


def has_editable_parameterized_skeleton_relation(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> bool:
    """Return whether same-skeleton evidence is strong enough for edit scoring.

    Same-skeleton literal/callee variants are real structural relations, but
    most should stay as maintenance-note evidence. Assessment treats them like
    editable parameterized helper clones only when the scored relation already proves
    near-identical body shape, same-role/local evidence, high refactorability,
    and low cost/risk.
    """

    relation_policy = policy.relation_evidence
    return (
        has_parameterized_skeleton_relation(metrics)
        and metrics.same_role_relation_count > 0
        and metrics.same_directory_relation_count > 0
        and metrics.max_tree_similarity
        >= relation_policy.parameterized_skeleton_min_tree_similarity
        and metrics.max_refactorability_score
        >= relation_policy.parameterized_skeleton_min_refactorability
        and metrics.max_abstraction_cost_score
        <= relation_policy.parameterized_skeleton_max_abstraction_cost
        and metrics.max_relation_risk_score <= relation_policy.parameterized_skeleton_max_risk
    )


def has_clean_clone_relation(metrics: FindingMetrics, policy: AssessmentPolicy) -> bool:
    return has_exact_clone_relation(metrics) or has_editable_parameterized_skeleton_relation(
        metrics,
        policy,
    )


__all__ = [
    "has_clean_clone_relation",
    "has_editable_parameterized_skeleton_relation",
    "has_exact_clone_relation",
    "has_parameterized_skeleton_relation",
    "has_relation_kind",
    "relation_count",
]
