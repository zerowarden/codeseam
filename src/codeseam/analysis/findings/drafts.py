from __future__ import annotations

from typing import Any, cast

from codeseam.analysis.clusters import Cluster
from codeseam.analysis.findings.common import dedupe
from codeseam.analysis.findings.constants import EVIDENCE_KIND_SIGNATURE_CLUSTER
from codeseam.analysis.findings.context import SignatureDraftContext
from codeseam.analysis.findings.definitions import FindingTargetType
from codeseam.analysis.findings.locations import line_span, signature_locations
from codeseam.analysis.findings.metrics import (
    cluster_semantic_role_counts,
    cluster_semantic_role_reasons,
    is_sync_async_cluster,
    relation_pair_member_count,
    semantic_role_member_metrics,
    structural_metrics,
    unique_pairs,
)
from codeseam.analysis.findings.models import (
    EvidenceItem,
    FindingDraft,
    FindingMetrics,
)
from codeseam.analysis.findings.promotion import (
    COMPONENT_TITLE_NAME_LIMIT,
    parent_promoted_components,
    promotable_components,
    promoted_component_drafts,
)
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.relations import (
    AbstractionKind,
    EvidenceKind,
)
from codeseam.analysis.relations.models import (
    RefactorAction,
    RelationKind,
    RelationPair,
)
from codeseam.analysis.signatures import NormalizationLevel
from codeseam.caveat_msg import EVIDENCE_CAVEATS


def build_signature_drafts(
    signature_clusters: tuple[Cluster, ...],
    *,
    semantic_evidence: SemanticEvidenceIndex | None = None,
) -> list[FindingDraft]:
    targets = []
    semantic_evidence = semantic_evidence or SemanticEvidenceIndex.from_run(None)
    for cluster in signature_clusters:
        ctx = _signature_draft_context(cluster, semantic_evidence)
        targets.append(_signature_cluster_draft(ctx))
        targets.extend(promoted_component_drafts(ctx))
    return targets


def _signature_draft_context(
    cluster: Cluster,
    semantic_evidence: SemanticEvidenceIndex,
) -> SignatureDraftContext:
    enrichment = cluster.enrichment
    structural_pairs = list(enrichment.structural_duplicate_pairs if enrichment else ())
    # A pair that cleared the relatedness floor but matched no relation kind is a
    # similarity signal, not structural evidence: it must not profile the cluster.
    relation_pairs = [
        pair
        for pair in (enrichment.structural_relation_pairs if enrichment else ())
        if pair.relation_kind is not RelationKind.NONE
    ]
    subclusters = list(enrichment.structural_subclusters if enrichment else ())
    sync_async_cluster = is_sync_async_cluster(cluster)
    members = tuple(member.signature for member in cluster.members)
    all_relation_pairs = unique_pairs(structural_pairs, relation_pairs)
    return SignatureDraftContext(
        cluster=cluster,
        members=members,
        files=dedupe(member.file for member in members),
        evidence_kinds=list(enrichment.evidence_kinds if enrichment else ()),
        callsite_patterns=list(enrichment.callsite_patterns if enrichment else ()),
        abstraction_risks=list(enrichment.abstraction_risks if enrichment else ()),
        structural_pairs=structural_pairs,
        relation_pairs=relation_pairs,
        promoted_components=promotable_components(relation_pairs),
        subclusters=subclusters,
        actions=list(enrichment.refactor_action_candidates if enrichment else ()),
        action_summary=enrichment.refactor_action_summary if enrichment else None,
        candidate_generation=enrichment.candidate_generation if enrichment else None,
        structural_metrics=structural_metrics(structural_pairs, relation_pairs, subclusters),
        normalization_level=cluster.normalization_level,
        locations=signature_locations(cluster),
        sync_async_cluster=sync_async_cluster,
        semantic_role_counts=cluster_semantic_role_counts(
            cluster,
            sync_async_cluster=sync_async_cluster,
        ),
        semantic_role_reasons=cluster_semantic_role_reasons(
            cluster,
            sync_async_cluster=sync_async_cluster,
        ),
        semantic_role_member_metrics=semantic_role_member_metrics(
            members,
            member_count=cluster.member_count,
            sync_async_surface=sync_async_cluster,
        ),
        semantic_evidence=semantic_evidence.metrics_for_members(
            members,
            relation_pairs=all_relation_pairs,
        ),
        semantic_evidence_index=semantic_evidence,
    )


def _signature_cluster_draft(ctx: SignatureDraftContext) -> FindingDraft:
    cluster = ctx.cluster
    enrichment = cluster.enrichment
    promoted_pairs = [pair for component in parent_promoted_components(ctx) for pair in component]
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=_signature_title(cluster),
        severity="medium" if ctx.structural_pairs or ctx.relation_pairs else "low",
        confidence=float(enrichment.confidence if enrichment else 0.35),
        files=ctx.files,
        locations=ctx.locations,
        metrics=FindingMetrics(
            member_count=cluster.member_count,
            canonical_shape=cluster.canonical_shape,
            cluster_scope=cluster.cluster_scope,
            normalization_level=ctx.normalization_level,
            language_count=cluster.language_count,
            adapter_count=cluster.adapter_count,
            min_extraction_confidence=cluster.min_extraction_confidence,
            semantic_role_counts=ctx.semantic_role_counts,
            semantic_role_reasons=ctx.semantic_role_reasons,
            semantic_evidence=ctx.semantic_evidence,
            promoted_pair_count=len(promoted_pairs),
            promoted_member_count=relation_pair_member_count(promoted_pairs),
            pair_member_count=relation_pair_member_count(
                unique_pairs(ctx.structural_pairs, ctx.relation_pairs)
            ),
            **cast(Any, ctx.semantic_role_member_metrics),
            **ctx.structural_metrics,
        ),
        evidence=[
            EvidenceItem(EVIDENCE_KIND_SIGNATURE_CLUSTER, id=cluster.cluster_id),
            *[EvidenceItem(kind, id=cluster.cluster_id) for kind in ctx.evidence_kinds],
        ],
        reasons=_signature_reasons(
            ctx.structural_pairs,
            ctx.relation_pairs,
            ctx.actions,
            ctx.normalization_level,
            ctx.evidence_kinds,
        ),
        risk="low",
        direction=_signature_direction(ctx.relation_pairs or ctx.structural_pairs),
        overlaps={"signature_clusters": (cluster.cluster_id,)},
        member_count=cluster.member_count,
        has_signature_overlap=(
            not ctx.evidence_kinds or EvidenceKind.SIGNATURE_SHAPE_CLUSTER in ctx.evidence_kinds
        ),
        line_span=line_span(ctx.locations),
        non_claims=list(cluster.non_claims or EVIDENCE_CAVEATS),
        abstraction_kind=enrichment.abstraction_kind if enrichment else AbstractionKind.TRACK_ONLY,
        abstraction_risks=ctx.abstraction_risks,
        evidence_kinds=ctx.evidence_kinds,
        callsite_patterns=ctx.callsite_patterns,
        structural_relation_pairs=ctx.relation_pairs,
        structural_subclusters=ctx.subclusters,
        candidate_generation=ctx.candidate_generation,
        refactor_action_candidates=ctx.actions,
        refactor_action_summary=ctx.action_summary,
    )


def _signature_reasons(
    structural_pairs: list[RelationPair],
    relation_pairs: list[RelationPair],
    actions: list[RefactorAction],
    normalization_level: NormalizationLevel,
    evidence_kinds: list[str],
) -> list[str]:
    if EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in evidence_kinds:
        reasons = ["A typed wrapper normalizes one argument before the same downstream operation."]
    elif EvidenceKind.CONTENT_SIMILARITY in evidence_kinds:
        reasons = ["Functions with different signatures or sizes share distinctive content."]
    else:
        reasons = ["Multiple functions share the same normalized signature shape."]
    if normalization_level is not NormalizationLevel.SIGNATURE:
        reasons.append(
            f"Members also expose normalized {normalization_level.value} evidence for comparison."
        )
    if structural_pairs:
        reasons.append(
            "Small functions also have similar normalized names, matching roles, "
            "and similar normalized body structure."
        )
    if relation_pairs:
        reasons.append(
            "Pair-level relation evidence separates exact clones from divergent variants."
        )
    if actions:
        reasons.append("Refactor action candidates are derived from structural relation classes.")
    return reasons


def _signature_title(cluster: Cluster) -> str:
    shape = cluster.canonical_shape or "unknown"
    if cluster.enrichment and EvidenceKind.CONTENT_SIMILARITY in cluster.enrichment.evidence_kinds:
        names = dedupe(member.signature.symbol for member in cluster.members)
        shown = names[:COMPONENT_TITLE_NAME_LIMIT]
        more = f" +{len(names) - len(shown)}" if len(names) > len(shown) else ""
        return "Similar implementations " + " / ".join(shown) + more
    if (
        cluster.enrichment
        and EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in cluster.enrichment.evidence_kinds
    ):
        return f"Argument-normalization wrapper {shape}"
    if cluster.cluster_scope == "cross_language":
        return f"Cross-language analogous signature shape {shape}"
    if cluster.cluster_scope == "same_family":
        return f"Same-family analogous signature shape {shape}"
    return f"Shared signature shape {shape}"


def _signature_direction(structural_pairs: list[RelationPair]) -> str:
    if structural_pairs:
        return "Compare helper intent; extract or import a shared helper if behavior matches."
    return "Use as context only unless structural evidence reinforces it."


__all__ = ["build_signature_drafts"]
