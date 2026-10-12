"""Clone components promoted out of broad clusters into their own drafts."""

from __future__ import annotations

from typing import Any, cast

from codeseam.analysis.clusters import Cluster
from codeseam.analysis.findings.common import dedupe
from codeseam.analysis.findings.constants import EVIDENCE_KIND_SIGNATURE_CLUSTER
from codeseam.analysis.findings.context import SignatureDraftContext
from codeseam.analysis.findings.definitions import FindingTargetType
from codeseam.analysis.findings.locations import line_span
from codeseam.analysis.findings.metrics import (
    EXAMPLE_ROLES,
    PAIR_MEMBER_COUNT,
    member_ref_semantic_role_counts,
    pair_either_member_has_role_family,
    relation_pair_member_count,
    semantic_role_member_metrics,
    structural_metrics,
    sync_async_member_pair,
    sync_async_pair_reasons,
)
from codeseam.analysis.findings.models import (
    EvidenceItem,
    FindingDraft,
    FindingLocation,
    FindingMetrics,
)
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.relations import (
    AbstractionKind,
    CloneClass,
    EvidenceKind,
)
from codeseam.analysis.relations.actions import refactor_action_candidates
from codeseam.analysis.relations.models import (
    MemberRef,
    RelationPair,
)
from codeseam.analysis.relations.subclusters import subcluster_members
from codeseam.analysis.relations.summary import summarize_actions
from codeseam.analysis.semantic_roles import (
    API_SURFACE_ROLES,
    INTERFACE_ONLY_ROLES,
    PROTOCOL_SURFACE_ROLES,
)
from codeseam.caveat_msg import EVIDENCE_CAVEATS

PROMOTED_CLONE_TYPES = frozenset((CloneClass.TYPE_2_PARAMETERIZED, CloneClass.TYPE_3_NEAR_MISS))


# Same bar as a strong relation in assessment (assess.RELATION_STRONG_CONFIDENCE).
PROMOTED_RELATION_MIN_CONFIDENCE = 0.70


COMPONENT_TITLE_NAME_LIMIT = 3


GUARDED_PROMOTED_PAIR_MAX_BODY_LINES = 5


GUARDED_PROMOTED_PAIR_MIN_STABLE_STATEMENTS = 5


GUARDED_PROMOTION_ROLES = (
    INTERFACE_ONLY_ROLES | PROTOCOL_SURFACE_ROLES | API_SURFACE_ROLES | EXAMPLE_ROLES
)


def promoted_component_drafts(ctx: SignatureDraftContext) -> list[FindingDraft]:
    components = parent_promoted_components(ctx)
    drafts: list[FindingDraft] = []
    for index, pairs in enumerate(components, 1):
        members = subcluster_members(pairs)
        locations = _member_locations(members)
        has_exact_pair = any(pair.flags.body_hash_match for pair in pairs)
        actions = (
            list(pairs[0].refactor_action_candidates)
            if len(pairs) == 1
            else refactor_action_candidates(pairs, members)
        )
        drafts.append(
            FindingDraft(
                target_type=FindingTargetType.SIGNATURE_SHAPE,
                title=_component_title(pairs, members),
                severity="medium",
                confidence=float(max(pair.scores.confidence for pair in pairs)),
                files=dedupe(member.file for member in members),
                locations=locations,
                metrics=_component_metrics(ctx.cluster, pairs, ctx.semantic_evidence_index),
                evidence=[
                    EvidenceItem(EVIDENCE_KIND_SIGNATURE_CLUSTER, id=ctx.cluster.cluster_id),
                    EvidenceItem(
                        EvidenceKind.STRUCTURAL_DUPLICATE,
                        id=f"{ctx.cluster.cluster_id}:{index}",
                    ),
                ],
                reasons=[
                    "Clone relations were promoted out of a broader signature cluster.",
                    "The parent signature cluster may still be too broad for one refactor.",
                ],
                risk="low",
                direction=(
                    "Inspect these duplicates; consolidate only if semantic guardrails allow it."
                ),
                overlaps={"signature_clusters": (ctx.cluster.cluster_id,)},
                member_count=len(members),
                has_signature_overlap=True,
                line_span=line_span(locations),
                non_claims=list(ctx.cluster.non_claims or EVIDENCE_CAVEATS),
                abstraction_kind=AbstractionKind.EXTRACT_HELPER,
                evidence_kinds=[
                    EvidenceKind.SIGNATURE_SHAPE_CLUSTER,
                    *([EvidenceKind.STRUCTURAL_DUPLICATE] if has_exact_pair else []),
                ],
                structural_relation_pairs=pairs,
                refactor_action_candidates=actions,
                refactor_action_summary=summarize_actions(actions),
            )
        )
    return drafts


def should_promote(
    cluster: Cluster,
    components: list[list[RelationPair]],
    relation_pairs: list[RelationPair],
) -> bool:
    """Promote unless the parent cluster is itself one duplicate group.

    Several disjoint components are each narrower than the parent, even when
    together they cover every member.
    """

    promoted = [pair for component in components for pair in component]
    return bool(
        promoted
        and (
            len(components) > 1
            or relation_pair_member_count(promoted) < cluster.member_count
            or len(relation_pairs) > len(promoted)
        )
    )


def parent_promoted_components(ctx: SignatureDraftContext) -> list[list[RelationPair]]:
    if should_promote(ctx.cluster, ctx.promoted_components, ctx.relation_pairs):
        return ctx.promoted_components
    return []


def promotable_components(relation_pairs: list[RelationPair]) -> list[list[RelationPair]]:
    """Connected groups of clone pairs that deserve their own target.

    Exact pairs always qualify; near-miss clone pairs (type-2/3) qualify when the
    relation is strong. Without this, a real duplicate inside a broad signature
    bucket is only visible as part of the bucket's catch-all target.
    """

    return _pair_components([pair for pair in relation_pairs if _promotable(pair)])


def _promotable(pair: RelationPair) -> bool:
    if not pair.same_role or _guarded_exact_pair_needs_cluster_context(pair):
        return False
    if pair.flags.body_hash_match:
        return True
    return (
        pair.clone_type in PROMOTED_CLONE_TYPES
        and pair.scores.confidence >= PROMOTED_RELATION_MIN_CONFIDENCE
    )


def _pair_components(pairs: list[RelationPair]) -> list[list[RelationPair]]:
    parent: dict[tuple[str, int, str], tuple[str, int, str]] = {}

    def find(key: tuple[str, int, str]) -> tuple[str, int, str]:
        while parent.setdefault(key, key) != key:
            key = parent[key]
        return key

    for pair in pairs:
        parent[find(_member_key(pair.left))] = find(_member_key(pair.right))
    groups: dict[tuple[str, int, str], list[RelationPair]] = {}
    for pair in pairs:
        groups.setdefault(find(_member_key(pair.left)), []).append(pair)
    return sorted(
        (sorted(group, key=_pair_location_key) for group in groups.values()),
        key=lambda group: _pair_location_key(group[0]),
    )


def _member_key(member: MemberRef) -> tuple[str, int, str]:
    return member.file, member.start_line, member.symbol


def _pair_location_key(pair: RelationPair) -> tuple[tuple[str, int, str], tuple[str, int, str]]:
    return _member_key(pair.left), _member_key(pair.right)


def _guarded_exact_pair_needs_cluster_context(pair: RelationPair) -> bool:
    """Return whether exact pair evidence is safer inside the parent cluster.

    Promoted exact-pair targets are useful for ordinary helper clones, but tiny
    protocol/API/interface/example pairs often represent required surface area.
    Keeping them in the parent cluster preserves detection while avoiding extra
    standalone edit-looking targets.
    """

    if not pair_either_member_has_role_family(pair, GUARDED_PROMOTION_ROLES):
        return False
    return (
        pair_either_member_has_role_family(pair, INTERFACE_ONLY_ROLES | EXAMPLE_ROLES)
        or pair.min_body_line_count <= GUARDED_PROMOTED_PAIR_MAX_BODY_LINES
        or pair.anti_unification.stable_statement_count
        < GUARDED_PROMOTED_PAIR_MIN_STABLE_STATEMENTS
    )


def _component_title(pairs: list[RelationPair], members: list[MemberRef]) -> str:
    if len(pairs) == 1:
        pair = pairs[0]
        if pair.left.symbol and pair.left.symbol == pair.right.symbol:
            return f"Duplicate helper {pair.left.symbol}"
        left = pair.left.symbol or "left helper"
        right = pair.right.symbol or "right helper"
        return f"Duplicate helper pair {left} / {right}"
    names = dedupe(member.symbol for member in members if member.symbol)
    if len(names) == 1:
        return f"Duplicate helper {names[0]} ({len(members)} copies)"
    shown = names[:COMPONENT_TITLE_NAME_LIMIT]
    more = f" +{len(names) - len(shown)}" if len(names) > len(shown) else ""
    return "Duplicate helpers " + " / ".join(shown) + more


def _member_locations(members: list[MemberRef]) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=member.file,
            start_line=member.start_line,
            end_line=member.end_line,
            source="structural_pair",
            kind="structural_duplicate",
            symbol=member.symbol,
            message="Promoted clone relation from a broader signature cluster.",
            container=member.container,
        )
        for member in members
    ]


def _component_metrics(
    cluster: Cluster,
    pairs: list[RelationPair],
    semantic_evidence: SemanticEvidenceIndex,
) -> FindingMetrics:
    """Metrics for a promoted clone component; exact (body-hash) pairs count as duplicates."""

    members = subcluster_members(pairs)
    sync_async = len(members) == PAIR_MEMBER_COUNT and sync_async_member_pair(*members)
    return FindingMetrics(
        member_count=len(members),
        canonical_shape=cluster.canonical_shape,
        cluster_scope=cluster.cluster_scope,
        normalization_level=cluster.normalization_level,
        language_count=cluster.language_count,
        adapter_count=cluster.adapter_count,
        min_extraction_confidence=cluster.min_extraction_confidence,
        semantic_role_counts=member_ref_semantic_role_counts(
            tuple(members), sync_async_pair=sync_async
        ),
        semantic_role_reasons=tuple(
            dict.fromkeys(
                [
                    *(reason for member in members for reason in member.semantic_role_reasons),
                    *sync_async_pair_reasons(sync_async),
                ]
            )
        ),
        semantic_evidence=semantic_evidence.metrics_for_members(
            tuple(members), relation_pairs=tuple(pairs)
        ),
        **cast(
            Any,
            semantic_role_member_metrics(
                tuple(members),
                member_count=len(members),
                sync_async_surface=sync_async,
            ),
        ),
        **structural_metrics([pair for pair in pairs if pair.flags.body_hash_match], pairs, []),
    )


__all__ = [
    "COMPONENT_TITLE_NAME_LIMIT",
    "GUARDED_PROMOTED_PAIR_MAX_BODY_LINES",
    "GUARDED_PROMOTED_PAIR_MIN_STABLE_STATEMENTS",
    "GUARDED_PROMOTION_ROLES",
    "PROMOTED_CLONE_TYPES",
    "PROMOTED_RELATION_MIN_CONFIDENCE",
    "parent_promoted_components",
    "promotable_components",
    "promoted_component_drafts",
    "should_promote",
]
