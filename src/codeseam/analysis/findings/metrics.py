"""Metrics that summarize a cluster's relation pairs and semantic roles for a draft."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from codeseam.analysis.clusters import Cluster
from codeseam.analysis.relations.models import RelationPair
from codeseam.analysis.semantic_roles import (
    API_SURFACE_ROLES,
    DECLARATION_SURFACE_ROLES,
    INTERFACE_ONLY_ROLES,
    PROTOCOL_SURFACE_ROLES,
    FunctionSemanticRole,
    role_counts,
    sync_async_mirror_members,
    sync_async_mirror_pair,
)
from codeseam.platform import parent_path

PAIR_MEMBER_COUNT = 2


CONSTRUCTOR_ROLES = frozenset({FunctionSemanticRole.CONSTRUCTOR})


EXAMPLE_ROLES = frozenset({FunctionSemanticRole.EXAMPLE_CODE})


TEST_ROLES = frozenset({FunctionSemanticRole.TEST_CODE})


@dataclass(frozen=True, slots=True)
class RelationRoleCounts:
    constructor: int = 0
    example: int = 0
    test: int = 0
    declaration: int = 0
    interface_only: int = 0
    protocol: int = 0
    api_surface: int = 0


def cluster_semantic_role_counts(
    cluster: Cluster,
    *,
    sync_async_cluster: bool,
) -> dict[str, int]:
    roles = [
        role
        for member in cluster.members
        for role in getattr(member.signature, "semantic_roles", ())
    ]
    if sync_async_cluster:
        roles.append(FunctionSemanticRole.SYNC_ASYNC_MIRROR.value)
    return role_counts(roles)


def cluster_semantic_role_reasons(
    cluster: Cluster,
    *,
    sync_async_cluster: bool,
) -> tuple[str, ...]:
    reasons = [
        reason
        for member in cluster.members
        for reason in getattr(member.signature, "semantic_role_reasons", ())
    ]
    if sync_async_cluster:
        reasons.append("matching symbols appear across sync and async path boundaries")
    return tuple(dict.fromkeys(reasons))


def member_ref_semantic_role_counts(
    members: tuple[object, ...],
    *,
    sync_async_pair: bool,
) -> dict[str, int]:
    roles = [role for member in members for role in getattr(member, "semantic_roles", ())]
    if len(members) == PAIR_MEMBER_COUNT and sync_async_pair:
        roles.append(FunctionSemanticRole.SYNC_ASYNC_MIRROR.value)
    return role_counts(roles)


def sync_async_pair_reasons(sync_async_pair: bool) -> tuple[str, ...]:
    return (
        ("matching symbols appear across sync and async path boundaries",)
        if sync_async_pair
        else ()
    )


def structural_metrics(
    pairs: list[RelationPair],
    relation_pairs: list[RelationPair],
    subclusters: Sequence[object],
) -> dict[str, Any]:
    if not pairs and not relation_pairs and not subclusters:
        return {}
    all_pairs = unique_pairs(pairs, relation_pairs)
    if not all_pairs:
        return {
            "structural_duplicate_pair_count": 0,
            "structural_relation_pair_count": 0,
        }
    lead = lead_pair(all_pairs)
    duplicate_role_counts = _relation_role_counts(pairs)
    relation_role_counts = _relation_role_counts(all_pairs)
    min_body_line_counts = [
        pair.min_body_line_count for pair in all_pairs if type(pair.min_body_line_count) is int
    ]
    metrics: dict[str, Any] = {
        "structural_duplicate_pair_count": len(pairs),
        "structural_relation_pair_count": len(relation_pairs),
        "body_hash_match_count": sum(1 for pair in all_pairs if pair.flags.body_hash_match),
        "relation_kind_counts": _relation_kind_counts(all_pairs),
        "delta_kind_counts": _delta_counts(all_pairs),
        "same_role_relation_count": sum(1 for pair in all_pairs if pair.same_role),
        "same_directory_relation_count": sum(1 for pair in all_pairs if _same_directory_pair(pair)),
        "guardrail_relation_pair_count": len(all_pairs),
        "constructor_duplicate_pair_count": duplicate_role_counts.constructor,
        "constructor_relation_pair_count": relation_role_counts.constructor,
        "example_duplicate_pair_count": duplicate_role_counts.example,
        "example_relation_pair_count": relation_role_counts.example,
        "test_duplicate_pair_count": duplicate_role_counts.test,
        "test_relation_pair_count": relation_role_counts.test,
        "declaration_duplicate_pair_count": duplicate_role_counts.declaration,
        "declaration_relation_pair_count": relation_role_counts.declaration,
        "interface_only_duplicate_pair_count": duplicate_role_counts.interface_only,
        "protocol_duplicate_pair_count": duplicate_role_counts.protocol,
        "api_surface_duplicate_pair_count": duplicate_role_counts.api_surface,
        "interface_only_relation_pair_count": relation_role_counts.interface_only,
        "protocol_relation_pair_count": relation_role_counts.protocol,
        "api_surface_relation_pair_count": relation_role_counts.api_surface,
        # One relation's profile comes from one pair, never from several pairs' maxima.
        **_lead_pair_metrics(lead),
        # Extent guards stay cluster-wide on purpose: they bound every member.
        "max_body_line_count": max(pair.max_body_line_count for pair in all_pairs),
        "min_stable_statement_count": min(
            pair.anti_unification.stable_statement_count for pair in all_pairs
        ),
    }
    if min_body_line_counts:
        metrics["min_body_line_count"] = min(min_body_line_counts)
    return metrics


def unique_pairs(*groups: Sequence[RelationPair]) -> list[RelationPair]:
    """Merge pair groups without double counting (duplicate pairs are a subset of relations)."""

    return list({id(pair): pair for group in groups for pair in group}.values())


def lead_pair(pairs: Sequence[RelationPair]) -> RelationPair:
    """The pair a cluster's score profile is taken from: highest confidence, then location."""

    return min(
        pairs,
        key=lambda pair: (
            -pair.scores.confidence,
            -pair.scores.relatedness,
            -pair.scores.refactorability,
            pair.left.file,
            pair.left.start_line,
            pair.right.file,
            pair.right.start_line,
        ),
    )


def _lead_pair_metrics(pair: RelationPair) -> dict[str, Any]:
    return {
        "lead_tree_similarity": round(pair.tree.tree_similarity, 4),
        "lead_relatedness_score": round(pair.scores.relatedness, 4),
        "lead_refactorability_score": round(pair.scores.refactorability, 4),
        "lead_abstraction_cost_score": round(pair.scores.abstraction_cost, 4),
        "lead_risk_score": round(pair.scores.risk, 4),
        "lead_confidence_score": round(pair.scores.confidence, 4),
        "lead_stable_statement_count": pair.anti_unification.stable_statement_count,
        "lead_hole_count": pair.anti_unification.hole_count,
        "lead_hole_size": pair.anti_unification.max_hole_size,
    }


def _relation_kind_counts(pairs: list[RelationPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.relation_kind.value] = counts.get(pair.relation_kind.value, 0) + 1
    return counts


def _delta_counts(pairs: list[RelationPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        for delta in pair.delta_kinds:
            counts[delta.value] = counts.get(delta.value, 0) + 1
    return counts


def _same_directory_pair(pair: RelationPair) -> bool:
    return parent_path(pair.left.file) == parent_path(pair.right.file)


def is_sync_async_cluster(cluster: Cluster) -> bool:
    return sync_async_mirror_members(
        (
            member.signature.normalized_symbol or member.signature.symbol,
            member.signature.file,
        )
        for member in cluster.members
    )


def sync_async_member_pair(left: object, right: object) -> bool:
    return sync_async_mirror_pair(
        left_symbol=str(getattr(left, "normalized_symbol", "") or getattr(left, "symbol", "")),
        left_file=str(getattr(left, "file", "")),
        right_symbol=str(getattr(right, "normalized_symbol", "") or getattr(right, "symbol", "")),
        right_file=str(getattr(right, "file", "")),
    )


def relation_pair_member_count(pairs: list[RelationPair]) -> int:
    return len(
        {
            (
                member.signature_id,
                member.file,
                member.start_line,
                member.symbol,
            )
            for pair in pairs
            for member in (pair.left, pair.right)
        }
    )


def semantic_role_member_metrics(
    members: tuple[object, ...],
    *,
    member_count: int,
    sync_async_surface: bool,
) -> dict[str, int]:
    member_roles = [_member_roles(member) for member in members]
    return {
        "interface_only_member_count": _members_with_roles(
            member_roles,
            INTERFACE_ONLY_ROLES,
        ),
        "declaration_member_count": _members_with_roles(
            member_roles,
            DECLARATION_SURFACE_ROLES,
        ),
        "example_member_count": _members_with_roles(
            member_roles,
            frozenset({FunctionSemanticRole.EXAMPLE_CODE}),
        ),
        "test_member_count": _members_with_roles(
            member_roles,
            frozenset({FunctionSemanticRole.TEST_CODE}),
        ),
        "protocol_member_count": _members_with_roles(
            member_roles,
            PROTOCOL_SURFACE_ROLES,
        ),
        "api_surface_member_count": (
            member_count
            if sync_async_surface
            else _members_with_roles(member_roles, API_SURFACE_ROLES)
        ),
    }


def _member_roles(member: object) -> frozenset[str]:
    source = getattr(member, "signature", member)
    return frozenset(getattr(source, "semantic_roles", ()))


def _members_with_roles(
    member_roles: list[frozenset[str]],
    target_roles: frozenset[str],
) -> int:
    return sum(1 for roles in member_roles if roles & target_roles)


def _relation_role_counts(pairs: Iterable[RelationPair]) -> RelationRoleCounts:
    constructor = 0
    example = 0
    test = 0
    declaration = 0
    interface_only = 0
    protocol = 0
    api_surface = 0
    for pair in pairs:
        left_roles = _member_roles(pair.left)
        right_roles = _member_roles(pair.right)
        both_roles = left_roles & right_roles
        constructor += int(bool(both_roles & CONSTRUCTOR_ROLES))
        example += int(bool(both_roles & EXAMPLE_ROLES))
        test += int(bool(both_roles & TEST_ROLES))
        declaration += int(bool(both_roles & DECLARATION_SURFACE_ROLES))
        interface_only += int(bool(both_roles & INTERFACE_ONLY_ROLES))
        protocol += int(bool(both_roles & PROTOCOL_SURFACE_ROLES))
        api_surface += int(
            sync_async_member_pair(pair.left, pair.right) or bool(both_roles & API_SURFACE_ROLES)
        )
    return RelationRoleCounts(
        constructor=constructor,
        example=example,
        test=test,
        declaration=declaration,
        interface_only=interface_only,
        protocol=protocol,
        api_surface=api_surface,
    )


def pair_either_member_has_role_family(
    pair: RelationPair,
    target_roles: frozenset[str],
) -> bool:
    return bool((_member_roles(pair.left) | _member_roles(pair.right)) & target_roles)


__all__ = [
    "CONSTRUCTOR_ROLES",
    "EXAMPLE_ROLES",
    "PAIR_MEMBER_COUNT",
    "RelationRoleCounts",
    "TEST_ROLES",
    "cluster_semantic_role_counts",
    "cluster_semantic_role_reasons",
    "lead_pair",
    "member_ref_semantic_role_counts",
    "pair_either_member_has_role_family",
    "relation_pair_member_count",
    "semantic_role_member_metrics",
    "structural_metrics",
    "is_sync_async_cluster",
    "sync_async_member_pair",
    "sync_async_pair_reasons",
    "unique_pairs",
]
