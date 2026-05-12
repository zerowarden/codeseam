from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

from codeseam.analysis.assessment.cluster import (
    CandidateGenerationSummary,
    ClusterEnrichment,
    ClusterSummary,
    LineRange,
)
from codeseam.analysis.assessment.context import classify_contexts
from codeseam.analysis.relations.actions import pair_actions, refactor_action_candidates
from codeseam.analysis.relations.callables import (
    callable_members,
    callsite_evidence_kinds,
    callsite_patterns,
)
from codeseam.analysis.relations.candidates import (
    relation_candidate_members,
    relation_candidate_pairs,
)
from codeseam.analysis.relations.models import (
    EvidenceKind,
    MemberFeatureCache,
    MemberInput,
    RelationMemberContext,
    RelationPair,
)
from codeseam.analysis.relations.pairs import (
    ActionBuilder,
    TreeEditBudget,
    relation_pairs,
    structural_duplicate_pairs,
)
from codeseam.analysis.relations.policy import STRUCTURAL_POLICY
from codeseam.analysis.relations.risks import abstraction_kind, abstraction_risks, confidence_for
from codeseam.analysis.relations.subclusters import structural_subclusters
from codeseam.analysis.relations.summary import summarize_actions
from codeseam.analysis.signatures import CallsitePattern, SignatureAnalysis, signature_analysis_key
from codeseam.platform import Json, cached_identifier_tokens, dedupe, json_int, text

CANDIDATE_GENERATION_METHODS = (
    "signature_shape_bucket",
    "ast_shape_hash",
    "name_token_bucket",
    "call_fingerprint_overlap",
    "payload_builder_terminal_call",
    "bounded_pair_buckets",
    "cheap_pre_tree_gate",
)


class RelationPairBuilder(Protocol):
    def __call__(
        self,
        candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
        *,
        action_builder: ActionBuilder,
        feature_cache: MemberFeatureCache,
        stats: dict[str, int],
        tree_edit_budget: TreeEditBudget,
    ) -> list[RelationPair]: ...


type RelationFeatureHydrator = Callable[[Sequence[SignatureAnalysis]], list[SignatureAnalysis]]


def enrich_signature_cluster(  # noqa: PLR0913
    members: Sequence[SignatureAnalysis],
    *,
    base_evidence_kind: str = EvidenceKind.SIGNATURE_SHAPE_CLUSTER,
    candidate_scope: str = "within_signature_shape_bucket",
    extra_candidate_methods: list[str] | None = None,
    relation_pair_builder: RelationPairBuilder | None = None,
    tree_edit_budget: TreeEditBudget | None = None,
    feature_hydrator: RelationFeatureHydrator | None = None,
) -> ClusterEnrichment:
    enrichment_started = time.perf_counter()
    member_contexts = tuple(_member_mapping(member) for member in members)
    callables = callable_members(member_contexts)
    callsites = callsite_patterns(member_contexts)
    feature_cache = MemberFeatureCache(members)
    candidate_started = time.perf_counter()
    candidate_members = relation_candidate_members(members, feature_cache)
    candidate_pairs = relation_candidate_pairs(candidate_members, feature_cache)
    candidate_ms = _elapsed_ms(candidate_started)
    candidate_pairs = _hydrate_candidate_pairs(candidate_pairs, feature_hydrator)
    feature_cache = MemberFeatureCache(tuple(member for pair in candidate_pairs for member in pair))
    comparison_stats: dict[str, int] = {}
    relation_started = time.perf_counter()
    relation_items = (
        relation_pair_builder(
            candidate_pairs,
            action_builder=pair_actions,
            feature_cache=feature_cache,
            stats=comparison_stats,
            tree_edit_budget=tree_edit_budget or TreeEditBudget(),
        )
        if relation_pair_builder
        else relation_pairs(
            candidate_pairs,
            action_builder=pair_actions,
            feature_cache=feature_cache,
            stats=comparison_stats,
            tree_edit_budget=tree_edit_budget,
        )
    )
    relation_ms = _elapsed_ms(relation_started)
    structural_pairs = structural_duplicate_pairs(relation_items)
    member_features = feature_cache.entries(members)
    member_refs = tuple(features.ref for _, features in member_features)
    actions = refactor_action_candidates(relation_items, list(member_refs))
    evidence_kinds = cluster_evidence_kinds(
        callables,
        callsites,
        structural_pairs,
        base_evidence_kind=base_evidence_kind,
    )
    risks = abstraction_risks(member_contexts, evidence_kinds)
    confidence = confidence_for(evidence_kinds, risks)
    context_classifications = classify_contexts(
        [member.core for member in members],
        relation_items,
        structural_pairs,
    )
    return ClusterEnrichment(
        cluster_summary=cluster_summary(members, evidence_kinds, confidence, feature_cache),
        confidence=confidence,
        evidence_kinds=tuple(evidence_kinds),
        callable_factory_members=tuple(
            features.ref for _, features in member_features if features.member.return_type
        ),
        callsite_patterns=tuple(callsites),
        structural_relation_pairs=tuple(relation_items),
        structural_duplicate_pairs=tuple(structural_pairs),
        structural_subclusters=tuple(structural_subclusters(relation_items)),
        candidate_generation=candidate_generation_summary(
            members,
            candidate_members,
            candidate_pairs,
            feature_cache=feature_cache,
            options={
                "comparison_stats": {
                    **comparison_stats,
                    "profile_enrichment_ms": _elapsed_ms(enrichment_started),
                    "profile_candidate_ms": candidate_ms,
                    "profile_relation_ms": relation_ms,
                },
                "scope": candidate_scope,
                "extra_methods": extra_candidate_methods or [],
            },
        ),
        refactor_action_candidates=tuple(actions),
        refactor_action_summary=summarize_actions(actions),
        abstraction_kind=abstraction_kind(evidence_kinds, risks),
        abstraction_risks=tuple(risks),
        context_classifications=context_classifications,
    )


def _hydrate_candidate_pairs(
    candidate_pairs: list[tuple[MemberInput, MemberInput]],
    feature_hydrator: RelationFeatureHydrator | None,
) -> list[tuple[MemberInput, MemberInput]]:
    """Hydrate relation-detail features only after cheap candidate selection.

    Signature clustering and candidate generation use compact core features.
    Full graph/parameter/literal details are needed only for the pair scorer,
    so this keeps the cold path from reparsing every function in every cluster.
    """
    if feature_hydrator is None or not candidate_pairs:
        return candidate_pairs
    members = tuple(
        {
            signature_analysis_key(member): member
            for pair in candidate_pairs
            for member in pair
            if isinstance(member, SignatureAnalysis)
        }.values()
    )
    hydrated = {signature_analysis_key(member): member for member in feature_hydrator(members)}
    return [
        (
            _hydrated_member(left, hydrated),
            _hydrated_member(right, hydrated),
        )
        for left, right in candidate_pairs
    ]


def _hydrated_member(
    member: MemberInput,
    hydrated: dict[str, SignatureAnalysis],
) -> MemberInput:
    if isinstance(member, SignatureAnalysis):
        return hydrated.get(signature_analysis_key(member), member)
    return member


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def cluster_evidence_kinds(
    callables: Sequence[RelationMemberContext],
    callsites: Sequence[CallsitePattern],
    structural_pairs: object,
    *,
    base_evidence_kind: str = EvidenceKind.SIGNATURE_SHAPE_CLUSTER,
) -> list[str]:
    evidence_kinds: list[str] = [base_evidence_kind]
    if callables:
        evidence_kinds.append(EvidenceKind.CALLABLE_FACTORY)
    if structural_pairs:
        evidence_kinds.append(EvidenceKind.STRUCTURAL_DUPLICATE)
    evidence_kinds.extend(callsite_evidence_kinds(callsites))
    return sorted(dict.fromkeys(evidence_kinds))


def cluster_summary(
    members: Sequence[SignatureAnalysis],
    evidence_kinds: list[str],
    confidence: float,
    feature_cache: MemberFeatureCache,
) -> ClusterSummary:
    feature_members = [features.member for _, features in feature_cache.entries(members)]
    return ClusterSummary(
        member_count=len(feature_members),
        representative_files=tuple(
            str(file)
            for file in dedupe(member.file for member in feature_members if member.file)[
                : STRUCTURAL_POLICY.summary_limit
            ]
        ),
        representative_symbols=tuple(
            str(symbol)
            for symbol in dedupe(member.symbol for member in feature_members if member.symbol)[
                : STRUCTURAL_POLICY.summary_limit
            ]
        ),
        line_ranges=tuple(
            LineRange(
                file=member.file,
                start_line=member.start_line,
                end_line=member.end_line,
            )
            for member in feature_members[: STRUCTURAL_POLICY.summary_limit]
            if member.file and member.start_line
        ),
        evidence_kinds=tuple(evidence_kinds),
        confidence=confidence,
    )


def candidate_generation_summary(
    members: Sequence[SignatureAnalysis],
    candidate_members: Sequence[MemberInput],
    candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
    *,
    feature_cache: MemberFeatureCache,
    options: Json | None = None,
) -> CandidateGenerationSummary:
    options = options or {}
    scope = text(options.get("scope"), "within_signature_shape_bucket")
    extra_methods = options.get("extra_methods", [])
    extra_methods = extra_methods if isinstance(extra_methods, list) else []
    comparison_stats = options.get("comparison_stats", {})
    comparison_stats = comparison_stats if isinstance(comparison_stats, dict) else {}
    methods = [*CANDIDATE_GENERATION_METHODS, *(extra_methods or [])]
    member_features = feature_cache.entries(members)
    return CandidateGenerationSummary(
        methods=tuple(sorted(dict.fromkeys(methods))),
        implemented_scope=scope,
        member_count=len(members),
        eligible_member_count=len(candidate_members),
        candidate_pair_count=len(candidate_pairs),
        comparison_stats={str(key): json_int(value) for key, value in comparison_stats.items()},
        candidate_pair_limit=STRUCTURAL_POLICY.structural_pair_candidate_limit,
        bucket_member_limit=STRUCTURAL_POLICY.structural_bucket_member_limit,
        max_statement_count=STRUCTURAL_POLICY.max_statement_count,
        max_tree_node_count=STRUCTURAL_POLICY.max_tree_nodes,
        shape_hash_count=len({features.member.shape_hash for _, features in member_features}),
        body_hash_count=len({features.body_hash for _, features in member_features}),
        name_token_bucket_count=len(
            {cached_identifier_tokens(features.member.symbol) for _, features in member_features}
        ),
        call_fingerprint_token_count=len(
            {token for _, features in member_features for token in features.calls}
        ),
    )


def _member_mapping(member: SignatureAnalysis) -> RelationMemberContext:
    core = member.core
    output = member.output
    return RelationMemberContext(
        signature_id=core.signature_id,
        function_id=core.function_id,
        file=core.file,
        symbol=core.symbol,
        start_line=core.start_line,
        language=core.language,
        return_type=core.return_type,
        parameters=core.parameters,
        callsite_patterns=output.callsite_patterns,
        caveats=output.caveats,
        role=core.role,
    )
