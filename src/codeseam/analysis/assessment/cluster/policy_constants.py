from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from codeseam.analysis.assessment.cluster.models import PolicyConstantCluster
from codeseam.analysis.relations import (
    AbstractionKind,
    ActionKind,
    ActionStatus,
    EvidenceKind,
)
from codeseam.analysis.relations.models import RefactorAction, RefactorActionSummary
from codeseam.analysis.signatures import PolicyConstant
from codeseam.caveat_msg import POLICY_CONSTANT_CAVEATS
from codeseam.platform import clamp01, combine_product, parent_path, ramp_count

POLICY_CONSTANT_REVIEW_RELEVANCE = "duplicated_policy_constant"
POLICY_CONSTANT_PRIORITY_HINT = "high"
REASON_SAME_CONSTANT_NAME = "same_constant_name"
REASON_IDENTICAL_STRUCTURED_LITERAL = "identical_structured_literal_value"
SOURCE_ROLE = "source"


@dataclass(frozen=True, slots=True)
class PolicyConstantClusterPolicy:
    """Policy anchors for duplicated structured literals.

    Detection confidence is computed from exact grouped evidence and duplicate
    support. Action confidence is computed separately from the detected relation
    and ownership/locality hints, because centralizing a policy table is less
    certain than recognizing that two literals match.
    """

    member_support_high_at: int = 4
    specificity_preview_high_at: int = 120
    minimum_duplicate_support: float = 0.85
    minimum_structured_literal_specificity: float = 0.88
    source_role_multiplier: float = 1.0
    mixed_role_multiplier: float = 0.85
    same_directory_multiplier: float = 1.0
    cross_directory_multiplier: float = 0.82


POLICY_CONSTANT_CLUSTER_POLICY = PolicyConstantClusterPolicy()


def build_policy_constant_clusters(
    constants: list[PolicyConstant],
) -> list[PolicyConstantCluster]:
    grouped: dict[tuple[str, str, str], list[PolicyConstant]] = defaultdict(list)
    for constant in constants:
        grouped[
            (
                constant.language,
                constant.normalized_symbol,
                constant.literal_shape_hash,
            )
        ].append(constant)
    clusters: list[PolicyConstantCluster] = []
    for _, members in sorted(grouped.items()):
        if len(members) > 1:
            clusters.append(_cluster(len(clusters) + 1, members))
    return clusters


def _cluster(index: int, members: list[PolicyConstant]) -> PolicyConstantCluster:
    first = members[0]
    symbol = first.symbol
    cluster_id = f"polcl_{index:06d}"
    cluster_confidence = _cluster_confidence(members)
    action_confidence = _action_confidence(cluster_confidence, members)
    return PolicyConstantCluster(
        cluster_id=cluster_id,
        language=first.language,
        shape_hash=first.literal_shape_hash,
        canonical_shape=f"policy_constant({symbol}:{first.literal_kind})",
        members=tuple(sorted(members, key=lambda item: (item.file, item.start_line))),
        review_relevance=POLICY_CONSTANT_REVIEW_RELEVANCE,
        priority_hint=POLICY_CONSTANT_PRIORITY_HINT,
        confidence=cluster_confidence,
        evidence_kinds=(EvidenceKind.POLICY_CONSTANT_DUPLICATE,),
        abstraction_kind=AbstractionKind.MOVE_MODULE,
        refactor_action_candidates=(
            RefactorAction(
                kind=ActionKind.INTRODUCE_ABSTRACTION,
                status=ActionStatus.RECOMMENDED,
                confidence=action_confidence,
                applies_to=(),
                reason_codes=(
                    REASON_SAME_CONSTANT_NAME,
                    REASON_IDENTICAL_STRUCTURED_LITERAL,
                ),
            ),
        ),
        refactor_action_summary=RefactorActionSummary(
            primary_action=ActionKind.INTRODUCE_ABSTRACTION,
        ),
        non_claims=POLICY_CONSTANT_CAVEATS,
    )


def _cluster_confidence(
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy = POLICY_CONSTANT_CLUSTER_POLICY,
) -> float:
    return round(
        _exact_agreement(members)
        * (
            1.0
            - (1.0 - _literal_specificity(members, policy))
            * (1.0 - _member_support(members, policy))
        ),
        4,
    )


def _action_confidence(
    cluster_confidence: float,
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy = POLICY_CONSTANT_CLUSTER_POLICY,
) -> float:
    return round(
        combine_product(
            cluster_confidence,
            _role_ownership(members, policy),
            _locality(members, policy),
        ),
        4,
    )


def _exact_agreement(members: list[PolicyConstant]) -> float:
    return combine_product(
        _agreement_score(members, lambda item: item.language),
        _agreement_score(members, lambda item: item.normalized_symbol),
        _agreement_score(members, lambda item: item.literal_shape_hash),
        _agreement_score(members, lambda item: item.literal_kind),
    )


def _agreement_score(members: list[PolicyConstant], key: Callable[[PolicyConstant], str]) -> float:
    return 1.0 if len({key(member) for member in members}) == 1 else 0.0


def _literal_specificity(
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy,
) -> float:
    preview_score = max(
        ramp_count(
            len(member.literal_preview),
            starts_at=1,
            high_at=policy.specificity_preview_high_at,
        )
        for member in members
    )
    return clamp01(max(policy.minimum_structured_literal_specificity, preview_score))


def _member_support(
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy,
) -> float:
    support = ramp_count(
        len({(member.file, member.start_line, member.symbol) for member in members}),
        starts_at=2,
        high_at=policy.member_support_high_at,
    )
    return clamp01(max(policy.minimum_duplicate_support, support))


def _role_ownership(
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy,
) -> float:
    return (
        policy.source_role_multiplier
        if {member.role for member in members} == {SOURCE_ROLE}
        else policy.mixed_role_multiplier
    )


def _locality(
    members: list[PolicyConstant],
    policy: PolicyConstantClusterPolicy,
) -> float:
    directories = {parent_path(member.file) for member in members}
    return (
        policy.same_directory_multiplier
        if len(directories) <= 1
        else policy.cross_directory_multiplier
    )


__all__ = [
    "POLICY_CONSTANT_CLUSTER_POLICY",
    "PolicyConstantClusterPolicy",
    "build_policy_constant_clusters",
]
