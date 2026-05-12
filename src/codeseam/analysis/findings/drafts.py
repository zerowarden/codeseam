from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from codeseam.analysis.assessment import AbstractionRisk, ContextClassification
from codeseam.analysis.assessment.cluster import (
    CandidateGenerationSummary,
    Cluster,
    PolicyConstantCluster,
    StructuralSubcluster,
)
from codeseam.analysis.assessment.definitions import ExtractionConfidence, FindingTargetType
from codeseam.analysis.findings.common import dedupe
from codeseam.analysis.findings.constants import (
    EVIDENCE_KIND_POLICY_CONSTANT_CLUSTER,
    EVIDENCE_KIND_SIGNATURE_CLUSTER,
    EVIDENCE_OVERLAP_POLICY_CONSTANT,
)
from codeseam.analysis.findings.locations import line_span, signature_locations
from codeseam.analysis.findings.models import (
    EvidenceItem,
    FindingDraft,
    FindingLocation,
    FindingMetrics,
    SemanticEvidenceMetrics,
)
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.relations import (
    AbstractionKind,
    ActionKind,
    ActionStatus,
    EvidenceKind,
    RelationKind,
)
from codeseam.analysis.relations.models import (
    RefactorAction,
    RefactorActionSummary,
    RelationPair,
    member_ref,
)
from codeseam.analysis.relations.summary import summarize_actions
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
from codeseam.analysis.signatures import (
    CallsitePattern,
    IntraFunctionDuplicateBlock,
    NormalizationLevel,
    PolicyConstant,
    SignatureAnalysis,
    SignatureCore,
)
from codeseam.caveat_msg import EVIDENCE_CAVEATS
from codeseam.platform import parent_path

POLICY_CONSTANT_RELATEDNESS = 1.0
POLICY_CONSTANT_REFACTORABILITY = 0.92
POLICY_CONSTANT_CONFIDENCE = 0.98
POLICY_CONSTANT_RISK = 0.04
PROMOTED_PAIR_MEMBER_COUNT = 2
PAIR_MEMBER_COUNT = 2
GUARDED_PROMOTED_PAIR_MAX_BODY_LINES = 5
GUARDED_PROMOTED_PAIR_MIN_STABLE_STATEMENTS = 5
CONSTRUCTOR_ROLES = frozenset({FunctionSemanticRole.CONSTRUCTOR})
EXAMPLE_ROLES = frozenset({FunctionSemanticRole.EXAMPLE_CODE})
TEST_ROLES = frozenset({FunctionSemanticRole.TEST_CODE})
GUARDED_PROMOTION_ROLES = (
    INTERFACE_ONLY_ROLES | PROTOCOL_SURFACE_ROLES | API_SURFACE_ROLES | EXAMPLE_ROLES
)


@dataclass(frozen=True, slots=True)
class RelationRoleCounts:
    constructor: int = 0
    example: int = 0
    test: int = 0
    declaration: int = 0
    interface_only: int = 0
    protocol: int = 0
    api_surface: int = 0


@dataclass(frozen=True, slots=True)
class SignatureDraftContext:
    """Aggregated post-cache evidence needed to build finding drafts.

    This context is intentionally internal to draft construction.
    it only gives the reporting and assessment layer one coherent view
    of already-computed cluster evidence.
    """

    cluster: Cluster
    members: tuple[SignatureCore, ...]
    files: list[str]
    evidence_kinds: list[str]
    callsite_patterns: list[CallsitePattern]
    abstraction_risks: list[AbstractionRisk]
    structural_pairs: list[RelationPair]
    relation_pairs: list[RelationPair]
    promoted_pairs: list[RelationPair]
    subclusters: list[StructuralSubcluster]
    actions: list[RefactorAction]
    action_summary: RefactorActionSummary | None
    context_classifications: list[ContextClassification]
    candidate_generation: CandidateGenerationSummary | None
    structural_metrics: dict[str, Any]
    normalization_level: NormalizationLevel
    locations: list[FindingLocation]
    sync_async_cluster: bool
    semantic_role_counts: dict[str, int]
    semantic_role_reasons: tuple[str, ...]
    semantic_role_member_metrics: dict[str, int]
    semantic_evidence: SemanticEvidenceMetrics
    semantic_evidence_index: SemanticEvidenceIndex


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
        targets.extend(_promoted_structural_pair_drafts(ctx))
    return targets


def _signature_draft_context(
    cluster: Cluster,
    semantic_evidence: SemanticEvidenceIndex,
) -> SignatureDraftContext:
    enrichment = cluster.enrichment
    structural_pairs = list(enrichment.structural_duplicate_pairs if enrichment else ())
    relation_pairs = list(enrichment.structural_relation_pairs if enrichment else ())
    subclusters = list(enrichment.structural_subclusters if enrichment else ())
    sync_async_cluster = _sync_async_cluster(cluster)
    members = tuple(member.signature for member in cluster.members)
    all_relation_pairs = (*structural_pairs, *relation_pairs)
    return SignatureDraftContext(
        cluster=cluster,
        members=members,
        files=dedupe(member.file for member in members),
        evidence_kinds=list(enrichment.evidence_kinds if enrichment else ()),
        callsite_patterns=list(enrichment.callsite_patterns if enrichment else ()),
        abstraction_risks=list(enrichment.abstraction_risks if enrichment else ()),
        structural_pairs=structural_pairs,
        relation_pairs=relation_pairs,
        promoted_pairs=_promotable_exact_pairs(relation_pairs),
        subclusters=subclusters,
        actions=list(enrichment.refactor_action_candidates if enrichment else ()),
        action_summary=enrichment.refactor_action_summary if enrichment else None,
        context_classifications=list(enrichment.context_classifications if enrichment else ()),
        candidate_generation=enrichment.candidate_generation if enrichment else None,
        structural_metrics=_structural_metrics(structural_pairs, relation_pairs, subclusters),
        normalization_level=cluster.normalization_level,
        locations=signature_locations(cluster),
        sync_async_cluster=sync_async_cluster,
        semantic_role_counts=_cluster_semantic_role_counts(
            cluster,
            sync_async_cluster=sync_async_cluster,
        ),
        semantic_role_reasons=_cluster_semantic_role_reasons(
            cluster,
            sync_async_cluster=sync_async_cluster,
        ),
        semantic_role_member_metrics=_semantic_role_member_metrics(
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
    promoted_pairs = _parent_promoted_pairs(ctx)
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
            call_fingerprint_count=_member_feature_count(cluster, "call_tokens"),
            control_context_count=_member_feature_count(cluster, "control_context_vector"),
            semantic_role_counts=ctx.semantic_role_counts,
            semantic_role_reasons=ctx.semantic_role_reasons,
            semantic_evidence=ctx.semantic_evidence,
            promoted_exact_pair_count=len(promoted_pairs),
            promoted_exact_pair_member_count=_relation_pair_member_count(promoted_pairs),
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
        context_classifications=ctx.context_classifications,
    )


def build_policy_constant_drafts(
    clusters: tuple[PolicyConstantCluster, ...],
) -> list[FindingDraft]:
    targets = []
    for cluster in clusters:
        members = list(cluster.members)
        files = dedupe(member.file for member in members)
        evidence_kinds = list(cluster.evidence_kinds)
        actions = list(cluster.refactor_action_candidates)
        locations = _policy_constant_locations(members)
        targets.append(
            FindingDraft(
                target_type=FindingTargetType.SIGNATURE_SHAPE,
                title=f"Duplicated policy constant {_policy_constant_symbol(cluster)}",
                severity="high",
                confidence=float(cluster.confidence),
                files=files,
                locations=locations,
                metrics=FindingMetrics(
                    member_count=cluster.member_count,
                    canonical_shape=cluster.canonical_shape,
                    policy_constant_duplicate_count=1,
                    cluster_scope="same_language",
                    normalization_level=NormalizationLevel.LITERAL_POLICY,
                    language_count=1,
                    adapter_count=1,
                    min_extraction_confidence=ExtractionConfidence.HIGH,
                    structural_relation_pair_count=1,
                    same_role_relation_count=1,
                    max_name_similarity=1.0,
                    max_relatedness_score=POLICY_CONSTANT_RELATEDNESS,
                    max_refactorability_score=POLICY_CONSTANT_REFACTORABILITY,
                    max_relation_confidence_score=POLICY_CONSTANT_CONFIDENCE,
                    max_relation_risk_score=POLICY_CONSTANT_RISK,
                ),
                evidence=[
                    EvidenceItem(EVIDENCE_KIND_POLICY_CONSTANT_CLUSTER, id=cluster.cluster_id),
                    EvidenceItem(EvidenceKind.POLICY_CONSTANT_DUPLICATE, id=cluster.cluster_id),
                ],
                reasons=[
                    "Multiple source modules define the same top-level policy constant name.",
                    "The duplicated constants have identical structured literal values.",
                    "Policy ordering and ranking rules should have one source of truth.",
                ],
                risk="low",
                direction=(
                    "Move the policy literal to a shared common module or configuration source "
                    "and import it at each call site."
                ),
                overlaps={EVIDENCE_OVERLAP_POLICY_CONSTANT: (cluster.cluster_id,)},
                member_count=cluster.member_count,
                line_span=line_span(locations),
                non_claims=list(cluster.non_claims or EVIDENCE_CAVEATS),
                abstraction_kind=cluster.abstraction_kind or AbstractionKind.MOVE_MODULE,
                evidence_kinds=evidence_kinds or [EvidenceKind.POLICY_CONSTANT_DUPLICATE],
                refactor_action_candidates=actions,
                refactor_action_summary=cluster.refactor_action_summary,
            )
        )
    return targets


def build_intra_function_duplicate_drafts(
    signatures: Sequence[SignatureAnalysis],
) -> list[FindingDraft]:
    """Build findings for repeated blocks inside a single function.

    Cross-function clustering only sees whole functions. This draft path turns
    adapter-collected local block evidence into the same language-neutral
    assessment flow used by relation findings.
    """

    drafts: list[FindingDraft] = []
    for signature in signatures:
        core = signature.core
        for index, block in enumerate(core.intra_function_duplicate_blocks, 1):
            drafts.append(_intra_function_duplicate_draft(core, block, index))
    return drafts


def _intra_function_duplicate_draft(
    core: SignatureCore,
    block: IntraFunctionDuplicateBlock,
    index: int,
) -> FindingDraft:
    locations = _intra_function_duplicate_locations(core, block)
    action = RefactorAction(
        kind=ActionKind.EXTRACT_SMALL_HELPER,
        status=ActionStatus.RECOMMENDED,
        confidence=0.9,
        applies_to=(member_ref(core),),
        preconditions=("intra_function_duplicate_block",),
        reason_codes=("INTRA_FUNCTION_DUPLICATE_BLOCK",),
    )
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=f"Repeated local block in {core.symbol}",
        severity="medium",
        confidence=0.9,
        files=[core.file],
        locations=locations,
        metrics=FindingMetrics(
            member_count=1,
            canonical_shape=core.canonical_shape,
            cluster_scope="same_language",
            normalization_level=NormalizationLevel.CONTROL,
            language_count=1,
            adapter_count=1,
            min_extraction_confidence=ExtractionConfidence.HIGH,
            intra_function_duplicate_block_count=1,
            intra_function_duplicate_line_count=sum(
                occurrence.end_line - occurrence.start_line + 1 for occurrence in block.occurrences
            ),
            max_body_line_count=block.line_count,
            min_body_line_count=block.line_count,
            max_stable_statement_count=block.statement_count,
            min_stable_statement_count=block.statement_count,
            max_tree_similarity=1.0,
            max_relatedness_score=0.9,
            max_refactorability_score=0.85,
            max_relation_confidence_score=0.9,
            max_relation_risk_score=0.04,
            semantic_role_counts=role_counts(core.semantic_roles),
            semantic_role_reasons=tuple(core.semantic_role_reasons),
            **cast(
                Any,
                _semantic_role_member_metrics(
                    (core,),
                    member_count=1,
                    sync_async_surface=False,
                ),
            ),
        ),
        evidence=[
            EvidenceItem(
                EvidenceKind.INTRA_FUNCTION_DUPLICATE,
                id=f"{core.signature_id}:{index}:{block.fingerprint}",
            )
        ],
        reasons=[
            "The same normalized block appears more than once inside this function.",
            (
                "The duplicate is local, so extraction can be considered without changing "
                "module boundaries."
            ),
        ],
        risk="low",
        direction=(
            "Extract the repeated local block into a small helper only if it preserves "
            "the guard or error semantics."
        ),
        overlaps={"signatures": (core.signature_id,)},
        member_count=1,
        has_signature_overlap=False,
        line_span=line_span(locations),
        non_claims=[
            "The repeated block is local to one function.",
            "Extraction still needs a semantic check before editing guard or error handling.",
        ],
        abstraction_kind=AbstractionKind.EXTRACT_HELPER,
        evidence_kinds=[EvidenceKind.INTRA_FUNCTION_DUPLICATE],
        refactor_action_candidates=[action],
        refactor_action_summary=summarize_actions([action]),
    )


def _intra_function_duplicate_locations(
    core: SignatureCore,
    block: IntraFunctionDuplicateBlock,
) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=core.file,
            start_line=occurrence.start_line,
            end_line=occurrence.end_line,
            source="intra_function_duplicate",
            kind=block.kind,
            symbol=core.symbol,
            message="Repeated local block within this function.",
        )
        for occurrence in block.occurrences
    ]


def _signature_reasons(
    structural_pairs: list[RelationPair],
    relation_pairs: list[RelationPair],
    actions: list[RefactorAction],
    normalization_level: NormalizationLevel,
    evidence_kinds: list[str],
) -> list[str]:
    if EvidenceKind.ARGUMENT_NORMALIZATION_WRAPPER in evidence_kinds:
        reasons = ["A typed wrapper normalizes one argument before the same downstream operation."]
    else:
        reasons = ["Multiple functions share the same normalized signature shape."]
    if normalization_level is not NormalizationLevel.SIGNATURE:
        reasons.append(
            f"Members also expose normalized {normalization_level.value} evidence for comparison."
        )
    if structural_pairs:
        reasons.append(
            "Small functions also have similar normalized names, matching roles, "
            "and similar normalized body trees."
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


def _policy_constant_symbol(cluster: PolicyConstantCluster) -> str:
    if not cluster.members:
        return cluster.canonical_shape or "unknown"
    return cluster.members[0].symbol or "unknown"


def _promoted_structural_pair_drafts(
    ctx: SignatureDraftContext,
) -> list[FindingDraft]:
    promoted_pairs = ctx.promoted_pairs
    if not _should_promote_structural_pairs(ctx.cluster, promoted_pairs, ctx.relation_pairs):
        return []
    drafts: list[FindingDraft] = []
    for index, pair in enumerate(promoted_pairs, 1):
        locations = _relation_pair_locations(pair)
        actions = list(pair.refactor_action_candidates)
        action_summary = summarize_actions(actions)
        drafts.append(
            FindingDraft(
                target_type=FindingTargetType.SIGNATURE_SHAPE,
                title=_pair_title(pair),
                severity="medium",
                confidence=float(pair.scores.confidence),
                files=dedupe([pair.left.file, pair.right.file]),
                locations=locations,
                metrics=_pair_metrics(ctx.cluster, pair, ctx.semantic_evidence_index),
                evidence=[
                    EvidenceItem(EVIDENCE_KIND_SIGNATURE_CLUSTER, id=ctx.cluster.cluster_id),
                    EvidenceItem(
                        EvidenceKind.STRUCTURAL_DUPLICATE,
                        id=f"{ctx.cluster.cluster_id}:{index}",
                    ),
                ],
                reasons=[
                    "Exact or near-exact pair evidence was promoted out of a broader cluster.",
                    "The parent signature cluster may still be too broad for one refactor.",
                ],
                risk="low",
                direction=(
                    "Inspect this exact duplicate pair; consolidate only if semantic "
                    "guardrails allow it."
                ),
                overlaps={"signature_clusters": (ctx.cluster.cluster_id,)},
                member_count=PROMOTED_PAIR_MEMBER_COUNT,
                has_signature_overlap=True,
                line_span=line_span(locations),
                non_claims=list(ctx.cluster.non_claims or EVIDENCE_CAVEATS),
                abstraction_kind=AbstractionKind.EXTRACT_HELPER,
                evidence_kinds=[
                    EvidenceKind.SIGNATURE_SHAPE_CLUSTER,
                    EvidenceKind.STRUCTURAL_DUPLICATE,
                ],
                structural_relation_pairs=[pair],
                refactor_action_candidates=actions,
                refactor_action_summary=action_summary,
            )
        )
    return drafts


def _should_promote_structural_pairs(
    cluster: Cluster,
    promoted_pairs: list[RelationPair],
    relation_pairs: list[RelationPair],
) -> bool:
    return bool(
        promoted_pairs
        and (
            _relation_pair_member_count(promoted_pairs) < cluster.member_count
            or len(relation_pairs) > len(promoted_pairs)
        )
    )


def _parent_promoted_pairs(ctx: SignatureDraftContext) -> list[RelationPair]:
    if _should_promote_structural_pairs(ctx.cluster, ctx.promoted_pairs, ctx.relation_pairs):
        return ctx.promoted_pairs
    return []


def _promotable_exact_pairs(relation_pairs: list[RelationPair]) -> list[RelationPair]:
    return [
        pair
        for pair in relation_pairs
        if pair.same_role
        and pair.flags.body_hash_match
        and pair.relation_kind in {RelationKind.BODY_IDENTICAL, RelationKind.BODY_PARAMETERIZED}
        and not _guarded_exact_pair_needs_cluster_context(pair)
    ]


def _guarded_exact_pair_needs_cluster_context(pair: RelationPair) -> bool:
    """Return whether exact pair evidence is safer inside the parent cluster.

    Promoted exact-pair targets are useful for ordinary helper clones, but tiny
    protocol/API/interface/example pairs often represent required surface area.
    Keeping them in the parent cluster preserves detection while avoiding extra
    standalone edit-looking targets.
    """

    if not _pair_either_member_has_role_family(pair, GUARDED_PROMOTION_ROLES):
        return False
    return (
        _pair_either_member_has_role_family(pair, INTERFACE_ONLY_ROLES | EXAMPLE_ROLES)
        or pair.min_body_line_count <= GUARDED_PROMOTED_PAIR_MAX_BODY_LINES
        or pair.anti_unification.stable_statement_count
        < GUARDED_PROMOTED_PAIR_MIN_STABLE_STATEMENTS
    )


def _pair_title(pair: RelationPair) -> str:
    if pair.left.symbol and pair.left.symbol == pair.right.symbol:
        return f"Duplicate helper {pair.left.symbol}"
    left = pair.left.symbol or "left helper"
    right = pair.right.symbol or "right helper"
    return f"Duplicate helper pair {left} / {right}"


def _relation_pair_locations(pair: RelationPair) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=member.file,
            start_line=member.start_line,
            end_line=member.end_line,
            source="structural_pair",
            kind="structural_duplicate",
            symbol=member.symbol,
            message="Promoted exact duplicate pair from a broader signature cluster.",
        )
        for member in (pair.left, pair.right)
    ]


def _pair_metrics(
    cluster: Cluster,
    pair: RelationPair,
    semantic_evidence: SemanticEvidenceIndex,
) -> FindingMetrics:
    sync_async_pair = _sync_async_member_pair(pair.left, pair.right)
    role_counts = _relation_role_counts((pair,))
    semantic_role_counts = _member_ref_semantic_role_counts(
        (pair.left, pair.right),
        sync_async_pair=sync_async_pair,
    )
    semantic_role_reasons = tuple(
        dict.fromkeys(
            [
                *pair.left.semantic_role_reasons,
                *pair.right.semantic_role_reasons,
                *_sync_async_pair_reasons(sync_async_pair),
            ]
        )
    )
    return FindingMetrics(
        member_count=PROMOTED_PAIR_MEMBER_COUNT,
        canonical_shape=cluster.canonical_shape,
        cluster_scope=cluster.cluster_scope,
        normalization_level=cluster.normalization_level,
        language_count=cluster.language_count,
        adapter_count=cluster.adapter_count,
        min_extraction_confidence=cluster.min_extraction_confidence,
        structural_duplicate_pair_count=1,
        structural_relation_pair_count=1,
        body_hash_match_count=1 if pair.flags.body_hash_match else 0,
        max_name_similarity=round(pair.scores.name, 4),
        max_tree_similarity=round(pair.tree.tree_similarity, 4),
        relation_kind_counts={pair.relation_kind.value: 1},
        delta_kind_counts=_delta_counts([pair]),
        same_role_relation_count=1 if pair.same_role else 0,
        clone_type_counts={pair.clone_type.value: 1},
        max_relatedness_score=round(pair.scores.relatedness, 4),
        max_refactorability_score=round(pair.scores.refactorability, 4),
        max_abstraction_cost_score=round(pair.scores.abstraction_cost, 4),
        max_relation_risk_score=round(pair.scores.risk, 4),
        max_relation_confidence_score=round(pair.scores.confidence, 4),
        max_tree_node_count=pair.tree.tree_node_count,
        max_body_line_count=pair.max_body_line_count,
        min_body_line_count=pair.min_body_line_count,
        max_stable_statement_count=pair.anti_unification.stable_statement_count,
        min_stable_statement_count=pair.anti_unification.stable_statement_count,
        max_hole_count=pair.anti_unification.hole_count,
        max_hole_size=pair.anti_unification.max_hole_size,
        semantic_role_counts=semantic_role_counts,
        semantic_role_reasons=semantic_role_reasons,
        semantic_evidence=semantic_evidence.metrics_for_members(
            (pair.left, pair.right),
            relation_pairs=(pair,),
        ),
        **cast(
            Any,
            _semantic_role_member_metrics(
                (pair.left, pair.right),
                member_count=PAIR_MEMBER_COUNT,
                sync_async_surface=sync_async_pair,
            ),
        ),
        guardrail_relation_pair_count=1,
        constructor_duplicate_pair_count=role_counts.constructor,
        constructor_relation_pair_count=role_counts.constructor,
        example_duplicate_pair_count=role_counts.example,
        example_relation_pair_count=role_counts.example,
        test_duplicate_pair_count=role_counts.test,
        test_relation_pair_count=role_counts.test,
        declaration_duplicate_pair_count=role_counts.declaration,
        declaration_relation_pair_count=role_counts.declaration,
        interface_only_duplicate_pair_count=role_counts.interface_only,
        protocol_duplicate_pair_count=role_counts.protocol,
        api_surface_duplicate_pair_count=role_counts.api_surface,
        interface_only_relation_pair_count=role_counts.interface_only,
        protocol_relation_pair_count=role_counts.protocol,
        api_surface_relation_pair_count=role_counts.api_surface,
        same_directory_relation_count=1 if _same_directory_pair(pair) else 0,
    )


def _policy_constant_locations(members: list[PolicyConstant]) -> list[FindingLocation]:
    return [
        FindingLocation(
            file=member.file,
            start_line=member.start_line,
            end_line=member.end_line,
            source="policy_literal",
            kind="policy_constant",
            symbol=member.symbol,
            message="Duplicated top-level policy constant with identical literal value.",
        )
        for member in members
    ]


def _member_feature_count(cluster: Cluster, key: str) -> int:
    return sum(
        len(value)
        for member in cluster.members
        if isinstance(value := getattr(member.signature, key, ()), list | tuple)
    )


def _cluster_semantic_role_counts(
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


def _cluster_semantic_role_reasons(
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


def _member_ref_semantic_role_counts(
    members: tuple[object, ...],
    *,
    sync_async_pair: bool,
) -> dict[str, int]:
    roles = [role for member in members for role in getattr(member, "semantic_roles", ())]
    if len(members) == PAIR_MEMBER_COUNT and sync_async_pair:
        roles.append(FunctionSemanticRole.SYNC_ASYNC_MIRROR.value)
    return role_counts(roles)


def _sync_async_pair_reasons(sync_async_pair: bool) -> tuple[str, ...]:
    return (
        ("matching symbols appear across sync and async path boundaries",)
        if sync_async_pair
        else ()
    )


def _signature_direction(structural_pairs: list[RelationPair]) -> str:
    if structural_pairs:
        return "Compare helper intent; extract or import a shared helper if behavior matches."
    return "Use as context only unless structural evidence reinforces it."


def _structural_metrics(
    pairs: list[RelationPair],
    relation_pairs: list[RelationPair],
    subclusters: Sequence[object],
) -> dict[str, Any]:
    if not pairs and not relation_pairs and not subclusters:
        return {}
    all_relation_pairs = [*pairs, *relation_pairs]
    scored_pairs = all_relation_pairs
    if not scored_pairs:
        return {
            "structural_duplicate_pair_count": 0,
            "structural_relation_pair_count": 0,
        }
    name_scores = [pair.scores.name for pair in scored_pairs]
    tree_scores = [pair.tree.tree_similarity for pair in scored_pairs]
    stable_statement_counts = [
        pair.anti_unification.stable_statement_count for pair in all_relation_pairs
    ]
    hole_counts = [pair.anti_unification.hole_count for pair in relation_pairs]
    hole_sizes = [pair.anti_unification.max_hole_size for pair in relation_pairs]
    max_body_line_counts = [pair.max_body_line_count for pair in all_relation_pairs]
    min_body_line_counts = [
        pair.min_body_line_count
        for pair in all_relation_pairs
        if type(pair.min_body_line_count) is int
    ]
    duplicate_role_counts = _relation_role_counts(pairs)
    relation_role_counts = _relation_role_counts(all_relation_pairs)
    metrics: dict[str, Any] = {
        "structural_duplicate_pair_count": len(pairs),
        "structural_relation_pair_count": len(relation_pairs),
        "body_hash_match_count": sum(
            1 for pair in all_relation_pairs if pair.flags.body_hash_match
        ),
        "max_name_similarity": round(max(name_scores), 4),
        "max_tree_similarity": round(max(tree_scores), 4),
        "relation_kind_counts": _relation_kind_counts(all_relation_pairs),
        "delta_kind_counts": _delta_counts(all_relation_pairs),
        "same_role_relation_count": sum(1 for pair in all_relation_pairs if pair.same_role),
        "same_directory_relation_count": sum(
            1 for pair in all_relation_pairs if _same_directory_pair(pair)
        ),
        "guardrail_relation_pair_count": len(all_relation_pairs),
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
        "clone_type_counts": _clone_type_counts(all_relation_pairs),
    }
    _add_numeric_max(metrics, all_relation_pairs, "max_relatedness_score", "relatedness")
    _add_numeric_max(metrics, all_relation_pairs, "max_refactorability_score", "refactorability")
    _add_numeric_max(
        metrics,
        all_relation_pairs,
        "max_abstraction_cost_score",
        "abstraction_cost",
    )
    _add_numeric_max(metrics, all_relation_pairs, "max_relation_risk_score", "risk")
    _add_numeric_max(metrics, all_relation_pairs, "max_relation_confidence_score", "confidence")
    if node_counts := [pair.tree.tree_node_count for pair in scored_pairs]:
        metrics["max_tree_node_count"] = max(node_counts)
    if max_body_line_counts:
        metrics["max_body_line_count"] = max(max_body_line_counts)
    if min_body_line_counts:
        metrics["min_body_line_count"] = min(min_body_line_counts)
    if stable_statement_counts:
        metrics["max_stable_statement_count"] = max(stable_statement_counts)
        metrics["min_stable_statement_count"] = min(stable_statement_counts)
    if hole_counts:
        metrics["max_hole_count"] = max(hole_counts)
    if hole_sizes:
        metrics["max_hole_size"] = max(hole_sizes)
    return metrics


def _relation_kind_counts(pairs: list[RelationPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.relation_kind.value] = counts.get(pair.relation_kind.value, 0) + 1
    return counts


def _clone_type_counts(pairs: list[RelationPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair.clone_type.value] = counts.get(pair.clone_type.value, 0) + 1
    return counts


def _delta_counts(pairs: list[RelationPair]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        for delta in pair.delta_kinds:
            counts[delta.value] = counts.get(delta.value, 0) + 1
    return counts


def _same_directory_pair(pair: RelationPair) -> bool:
    return parent_path(pair.left.file) == parent_path(pair.right.file)


def _sync_async_cluster(cluster: Cluster) -> bool:
    return sync_async_mirror_members(
        (
            member.signature.normalized_symbol or member.signature.symbol,
            member.signature.file,
        )
        for member in cluster.members
    )


def _sync_async_member_pair(left: object, right: object) -> bool:
    return sync_async_mirror_pair(
        left_symbol=str(getattr(left, "normalized_symbol", "") or getattr(left, "symbol", "")),
        left_file=str(getattr(left, "file", "")),
        right_symbol=str(getattr(right, "normalized_symbol", "") or getattr(right, "symbol", "")),
        right_file=str(getattr(right, "file", "")),
    )


def _relation_pair_member_count(pairs: list[RelationPair]) -> int:
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


def _semantic_role_member_metrics(
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
            _sync_async_member_pair(pair.left, pair.right) or bool(both_roles & API_SURFACE_ROLES)
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


def _pair_either_member_has_role_family(
    pair: RelationPair,
    target_roles: frozenset[str],
) -> bool:
    return bool((_member_roles(pair.left) | _member_roles(pair.right)) & target_roles)


def _add_numeric_max(
    metrics: dict[str, Any],
    pairs: Iterable[RelationPair],
    metric_key: str,
    score_key: str,
) -> None:
    value = max((float(getattr(pair.scores, score_key)) for pair in pairs), default=None)
    if value is not None:
        metrics[metric_key] = round(value, 4)


__all__ = [
    "build_intra_function_duplicate_drafts",
    "build_policy_constant_drafts",
    "build_signature_drafts",
]
