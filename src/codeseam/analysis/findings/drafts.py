from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from codeseam.analysis.assessment import AbstractionRisk
from codeseam.analysis.assessment.cluster import (
    CandidateGenerationSummary,
    Cluster,
    PolicyConstantCluster,
    PolicyConstantMatch,
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
    CloneClass,
    EvidenceKind,
)
from codeseam.analysis.relations.actions import refactor_action_candidates
from codeseam.analysis.relations.blocks import SharedBlock, shared_blocks
from codeseam.analysis.relations.models import (
    MemberRef,
    RefactorAction,
    RefactorActionSummary,
    RelationKind,
    RelationPair,
    member_ref,
)
from codeseam.analysis.relations.subclusters import subcluster_members
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
# Unifying drifted copies changes what some callers get; unifying differently
# named copies asserts the names mean one rule. Either is a medium risk, above
# the introduction-risk ceiling, so it is recorded for review, never edited.
POLICY_CONSTANT_DIVERGENT_RISK = 0.35
POLICY_CONSTANT_MATCH_TEXT = {
    PolicyConstantMatch.IDENTICAL: (
        "Duplicated policy constant",
        "Multiple source modules define the same top-level policy constant name.",
        "The duplicated constants have identical structured literal values.",
    ),
    PolicyConstantMatch.DRIFTED: (
        "Drifted policy constant",
        "Multiple source modules define the same top-level policy constant name.",
        "The copies share most items but their values have diverged.",
    ),
    PolicyConstantMatch.SCATTERED: (
        "Scattered policy literal",
        "The same structured literal is defined under different constant names.",
        "The names may describe one rule, or unrelated rules that happen to agree.",
    ),
}
PROMOTED_CLONE_TYPES = frozenset((CloneClass.TYPE_2_PARAMETERIZED, CloneClass.TYPE_3_NEAR_MISS))
# Same bar as a strong relation in assessment (assess.RELATION_STRONG_CONFIDENCE).
PROMOTED_RELATION_MIN_CONFIDENCE = 0.70
COMPONENT_TITLE_NAME_LIMIT = 3
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
    promoted_components: list[list[RelationPair]]
    subclusters: list[StructuralSubcluster]
    actions: list[RefactorAction]
    action_summary: RefactorActionSummary | None
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
        targets.extend(_promoted_component_drafts(ctx))
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
    sync_async_cluster = _sync_async_cluster(cluster)
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
    promoted_pairs = [pair for component in _parent_promoted_components(ctx) for pair in component]
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
            promoted_member_count=_relation_pair_member_count(promoted_pairs),
            pair_member_count=_relation_pair_member_count(
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
        title, *reasons = POLICY_CONSTANT_MATCH_TEXT[cluster.match]
        targets.append(
            FindingDraft(
                target_type=FindingTargetType.SIGNATURE_SHAPE,
                title=f"{title} {_policy_constant_symbol(cluster)}",
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
                    lead_relatedness_score=POLICY_CONSTANT_RELATEDNESS,
                    lead_refactorability_score=POLICY_CONSTANT_REFACTORABILITY,
                    lead_confidence_score=POLICY_CONSTANT_CONFIDENCE,
                    lead_risk_score=(
                        POLICY_CONSTANT_RISK
                        if cluster.match is PolicyConstantMatch.IDENTICAL
                        else POLICY_CONSTANT_DIVERGENT_RISK
                    ),
                ),
                evidence=[
                    EvidenceItem(EVIDENCE_KIND_POLICY_CONSTANT_CLUSTER, id=cluster.cluster_id),
                    EvidenceItem(EvidenceKind.POLICY_CONSTANT_DUPLICATE, id=cluster.cluster_id),
                ],
                reasons=[*reasons, "Policy rules should have one source of truth."],
                risk="low" if cluster.match is PolicyConstantMatch.IDENTICAL else "medium",
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


def build_shared_block_drafts(
    signatures: Sequence[SignatureAnalysis], clusters: Sequence[Cluster]
) -> list[FindingDraft]:
    """Findings for statement blocks shared by otherwise different functions.

    Pairs already found as whole-function clones are skipped, so a clone is
    never reported twice. A pair that is only related as a whole (it differs
    too much to consolidate) can still share a block worth extracting.
    """

    related = {
        frozenset(
            (
                (pair.left.file, pair.left.start_line, pair.left.symbol),
                (pair.right.file, pair.right.start_line, pair.right.symbol),
            )
        )
        for cluster in clusters
        if cluster.enrichment is not None
        for pair in cluster.enrichment.structural_duplicate_pairs
    }
    cores = [signature.core for signature in signatures]
    return [_shared_block_draft(block) for block in shared_blocks(cores, related=related)]


def _shared_block_draft(block: SharedBlock) -> FindingDraft:
    members = block.members
    locations = [
        FindingLocation(
            file=item.member.file,
            start_line=item.start_line,
            end_line=item.end_line,
            source="shared_block",
            kind="duplicate_block",
            symbol=item.member.symbol,
            message="Statement block shared with other functions.",
            container=item.member.container or "",
        )
        for item in block.occurrences
    ]
    line_counts = [item.line_count for item in block.occurrences]
    action = RefactorAction(
        kind=ActionKind.EXTRACT_SMALL_HELPER,
        status=ActionStatus.RECOMMENDED,
        confidence=0.85,
        applies_to=tuple(member_ref(core) for core in members),
        preconditions=("shared_block",),
        reason_codes=("SHARED_BLOCK",),
    )
    names = " / ".join(dict.fromkeys(core.symbol for core in members))
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title=f"Shared block in {names}",
        severity="medium",
        confidence=0.85,
        files=list(dict.fromkeys(core.file for core in members)),
        locations=locations,
        metrics=FindingMetrics(
            member_count=len(members),
            canonical_shape=f"shared_block({block.statement_count} statements)",
            cluster_scope="same_language",
            normalization_level=NormalizationLevel.CONTROL,
            language_count=1,
            adapter_count=1,
            min_extraction_confidence=ExtractionConfidence.HIGH,
            duplicate_block_count=1,
            duplicate_block_line_count=sum(line_counts),
            max_body_line_count=max(line_counts),
            min_body_line_count=min(line_counts),
            lead_stable_statement_count=block.statement_count,
            min_stable_statement_count=min(item.length for item in block.occurrences),
            lead_tree_similarity=1.0,
            lead_relatedness_score=0.85,
            lead_refactorability_score=0.8,
            lead_confidence_score=0.85,
            # Statement keys abstract names and literal values, so the copies
            # may differ in data a helper would have to take as parameters.
            lead_risk_score=0.1,
            semantic_role_counts=role_counts(
                role for core in members for role in core.semantic_roles
            ),
            semantic_role_reasons=tuple(
                dict.fromkeys(reason for core in members for reason in core.semantic_role_reasons)
            ),
            **cast(
                Any,
                _semantic_role_member_metrics(
                    members, member_count=len(members), sync_async_surface=False
                ),
            ),
        ),
        evidence=[EvidenceItem(EvidenceKind.SHARED_BLOCK, id=block.fingerprint)],
        reasons=[
            f"A block of {block.statement_count} statements appears in {len(members)} functions.",
            "The functions differ elsewhere, so whole-function comparison does not pair them.",
        ],
        risk="low",
        direction=(
            "Extract the shared block into a helper that the functions call, passing in "
            "any names or values that differ between the copies."
        ),
        overlaps={"signatures": tuple(core.signature_id for core in members)},
        member_count=len(members),
        has_signature_overlap=False,
        line_span=line_span(locations),
        non_claims=[
            "Only the block is shared; the rest of each function is different.",
            "Copies may differ in names or literal values that a helper must take as parameters.",
        ],
        abstraction_kind=AbstractionKind.EXTRACT_HELPER,
        evidence_kinds=[EvidenceKind.SHARED_BLOCK],
        refactor_action_candidates=[action],
        refactor_action_summary=summarize_actions([action]),
    )


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
            duplicate_block_count=1,
            duplicate_block_line_count=sum(
                occurrence.end_line - occurrence.start_line + 1 for occurrence in block.occurrences
            ),
            max_body_line_count=block.line_count,
            min_body_line_count=block.line_count,
            lead_stable_statement_count=block.statement_count,
            min_stable_statement_count=block.statement_count,
            lead_tree_similarity=1.0,
            lead_relatedness_score=0.9,
            lead_refactorability_score=0.85,
            lead_confidence_score=0.9,
            lead_risk_score=0.04,
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
            container=core.container or "",
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


def _policy_constant_symbol(cluster: PolicyConstantCluster) -> str:
    symbols = dedupe(member.symbol for member in cluster.members if member.symbol)
    return " / ".join(symbols) or cluster.canonical_shape or "unknown"


def _promoted_component_drafts(ctx: SignatureDraftContext) -> list[FindingDraft]:
    components = _parent_promoted_components(ctx)
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
            or _relation_pair_member_count(promoted) < cluster.member_count
            or len(relation_pairs) > len(promoted)
        )
    )


def _parent_promoted_components(ctx: SignatureDraftContext) -> list[list[RelationPair]]:
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

    if not _pair_either_member_has_role_family(pair, GUARDED_PROMOTION_ROLES):
        return False
    return (
        _pair_either_member_has_role_family(pair, INTERFACE_ONLY_ROLES | EXAMPLE_ROLES)
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
    sync_async = len(members) == PAIR_MEMBER_COUNT and _sync_async_member_pair(*members)
    return FindingMetrics(
        member_count=len(members),
        canonical_shape=cluster.canonical_shape,
        cluster_scope=cluster.cluster_scope,
        normalization_level=cluster.normalization_level,
        language_count=cluster.language_count,
        adapter_count=cluster.adapter_count,
        min_extraction_confidence=cluster.min_extraction_confidence,
        semantic_role_counts=_member_ref_semantic_role_counts(
            tuple(members), sync_async_pair=sync_async
        ),
        semantic_role_reasons=tuple(
            dict.fromkeys(
                [
                    *(reason for member in members for reason in member.semantic_role_reasons),
                    *_sync_async_pair_reasons(sync_async),
                ]
            )
        ),
        semantic_evidence=semantic_evidence.metrics_for_members(
            tuple(members), relation_pairs=tuple(pairs)
        ),
        **cast(
            Any,
            _semantic_role_member_metrics(
                tuple(members),
                member_count=len(members),
                sync_async_surface=sync_async,
            ),
        ),
        **_structural_metrics([pair for pair in pairs if pair.flags.body_hash_match], pairs, []),
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


__all__ = [
    "build_intra_function_duplicate_drafts",
    "build_shared_block_drafts",
    "build_policy_constant_drafts",
    "build_signature_drafts",
]
