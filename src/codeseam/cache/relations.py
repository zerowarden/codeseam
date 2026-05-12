from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from codeseam.analysis import (
    PAIR_POLICY,
    AbstractionCostComponents,
    ActionBuilder,
    CachedRelationSummary,
    CloneClassification,
    MemberFeatureCache,
    MemberFeatures,
    MemberInput,
    MemberRef,
    RefactorabilityComponents,
    RelationBasis,
    RelationPair,
    RelationPairBuilder,
    SequenceSkeleton,
    TreeComparison,
    TreeEditBudget,
    feature_member_ref,
    relation_pair_from_features,
    tree_comparison_features,
)
from codeseam.cache.blobs import load_cache_blob
from codeseam.cache.context import AnalysisCacheContext
from codeseam.cache.main import CacheCodec
from codeseam.output.serializers.relations import relation_pair_from_payload
from codeseam.platform import increment_stat, sha256_text
from codeseam.version import (
    RELATION_PAIR_CACHE_KEY_SCHEMA,
    RELATION_PAIR_CACHE_VALUE_VERSION,
    RELATION_PAIR_CACHE_VERSION,
    RELATION_PAIR_GROUP_CACHE_KEY_SCHEMA,
    RELATION_PAIR_GROUP_CACHE_VALUE_VERSION,
    RELATION_PAIR_GROUP_CACHE_VERSION,
    RELATION_PAIR_REF_CACHE_KEY_SCHEMA,
    TREE_COMPARISON_CACHE_KEY_SCHEMA,
    TREE_COMPARISON_CACHE_VALUE_VERSION,
    TREE_COMPARISON_CACHE_VERSION,
)

RELATION_PAIR_CACHE_NAMESPACE = "relation_pairs"
RELATION_PAIR_GROUP_CACHE_NAMESPACE = "relation_pair_groups"
TREE_COMPARISON_CACHE_NAMESPACE = "tree_comparisons"
TREE_COMPARISON_CACHE_VALUE_LENGTH = 6

__all__ = [
    "cached_relation_pair_builder",
    "cached_relation_pairs",
    "cached_tree_comparison_provider",
    "relation_pair_cache_key",
    "relation_pair_group_cache_value",
    "relation_pair_ref_cache_key",
    "relation_pairs_from_group_cache_value",
    "tree_comparison_features",
]


@dataclass(frozen=True, slots=True)
class CachedRelationPairValue:
    pair: RelationPair | None


@dataclass(frozen=True, slots=True)
class _RelationPairCacheCodec(CacheCodec[CachedRelationPairValue]):
    namespace: str = RELATION_PAIR_CACHE_NAMESPACE

    def dump(self, value: CachedRelationPairValue) -> object:
        return relation_pair_cache_value(value.pair)

    def load(self, value: object) -> CachedRelationPairValue | None:
        cached, pair = relation_pair_from_cache_value(value)
        return CachedRelationPairValue(pair) if cached else None


_RELATION_PAIR_CACHE = _RelationPairCacheCodec()


@dataclass(frozen=True, slots=True)
class _RelationPairGroupCacheCodec(CacheCodec[tuple[CachedRelationSummary, ...]]):
    namespace: str = RELATION_PAIR_GROUP_CACHE_NAMESPACE

    def dump(self, value: tuple[CachedRelationSummary, ...]) -> object:
        return relation_pair_group_cache_value_from_summaries(value)

    def load(self, value: object) -> tuple[CachedRelationSummary, ...] | None:
        cached, summaries = relation_summaries_from_group_cache_value(value)
        return summaries if cached else None


@dataclass(frozen=True, slots=True)
class _TreeComparisonCacheCodec(CacheCodec[TreeComparison]):
    namespace: str = TREE_COMPARISON_CACHE_NAMESPACE

    def dump(self, value: TreeComparison) -> object:
        return tree_comparison_cache_value(value)

    def load(self, value: object) -> TreeComparison | None:
        cached, tree = tree_comparison_from_cache_value(value)
        return tree if cached else None


_RELATION_PAIR_GROUP_CACHE = _RelationPairGroupCacheCodec()
_TREE_COMPARISON_CACHE = _TreeComparisonCacheCodec()


def cached_relation_pair_builder(caches: AnalysisCacheContext | None) -> RelationPairBuilder | None:
    if caches is None:
        return None

    def build(
        candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
        *,
        action_builder: ActionBuilder,
        feature_cache: MemberFeatureCache,
        stats: dict[str, int],
        tree_edit_budget: TreeEditBudget,
    ) -> list[RelationPair]:
        return cached_relation_pairs(
            candidate_pairs,
            action_builder=action_builder,
            feature_cache=feature_cache,
            stats=stats,
            caches=caches,
            tree_edit_budget=tree_edit_budget,
        )

    return build


def cached_relation_pairs(  # noqa: PLR0913
    candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
    *,
    action_builder: ActionBuilder,
    feature_cache: MemberFeatureCache,
    stats: dict[str, int],
    caches: AnalysisCacheContext,
    tree_edit_budget: TreeEditBudget | None = None,
) -> list[RelationPair]:
    increment_stat(stats, "candidate_pair_count", len(candidate_pairs))
    if not candidate_pairs:
        return []
    candidate_members = [member for pair in candidate_pairs for member in pair]
    feature_by_member_id = {
        id(member): features for member, features in feature_cache.entries(candidate_members)
    }
    candidates = [
        (
            left,
            right,
            feature_by_member_id[id(left)],
            feature_by_member_id[id(right)],
        )
        for left, right in candidate_pairs
    ]
    cache_keys = [
        relation_pair_cache_key(left_features, right_features)
        for _, _, left_features, right_features in candidates
    ]
    group_cache_key = ""
    feature_by_cache_key: dict[str, tuple[MemberFeatures, MemberFeatures]] = {}
    for cache_key, (_, _, left_features, right_features) in zip(
        cache_keys,
        candidates,
        strict=True,
    ):
        feature_by_cache_key[cache_key] = (left_features, right_features)
        feature_by_cache_key[
            relation_pair_ref_cache_key(
                feature_member_ref(left_features),
                feature_member_ref(right_features),
            )
        ] = (left_features, right_features)
    if caches.relation_pair_enabled:
        group_cache_key = relation_pair_group_cache_key(cache_keys)
        summaries = caches.cache(_RELATION_PAIR_GROUP_CACHE).get(group_cache_key)
        group_pairs = (
            relation_pairs_from_summaries(summaries, feature_by_cache_key)
            if summaries is not None
            else None
        )
        if group_pairs is not None:
            increment_stat(stats, "group_cache_hit_count")
            increment_stat(stats, "cache_hit_count", len(cache_keys))
            increment_stat(stats, "relation_pair_count", len(group_pairs))
            return list(group_pairs)
        increment_stat(stats, "group_cache_miss_count")
    cached_values: dict[str, CachedRelationPairValue] = {}
    if caches.relation_pair_enabled:
        cached_values = caches.cache(_RELATION_PAIR_CACHE).get_many(cache_keys)
    tree_comparison_provider = cached_tree_comparison_provider(caches, stats)
    pairs: list[RelationPair] = []
    relation_pair_payloads: dict[str, CachedRelationPairValue] = {}
    for cache_key, (_, _, left_features, right_features) in zip(
        cache_keys,
        candidates,
        strict=True,
    ):
        cached_value = cached_values.get(cache_key)
        if cached_value is None:
            increment_stat(stats, "cache_miss_count")
            pair = relation_pair_from_features(
                left_features,
                right_features,
                action_builder=action_builder,
                stats=stats,
                tree_edit_budget=tree_edit_budget,
                tree_comparison_provider=tree_comparison_provider,
            )
            if caches.relation_pair_enabled:
                relation_pair_payloads[cache_key] = CachedRelationPairValue(pair)
        else:
            increment_stat(stats, "cache_hit_count")
            pair = cached_value.pair
        if pair is not None:
            pairs.append(pair)
            increment_stat(stats, "scored_relation_pair_count")
    result = sorted(
        pairs,
        key=lambda item: (
            -item.scores.relatedness,
            -item.scores.refactorability,
            item.left.file,
            item.right.file,
        ),
    )[: PAIR_POLICY.relation_pair_limit]
    increment_stat(stats, "relation_pair_count", len(result))
    if caches.relation_pair_enabled and relation_pair_payloads:
        caches.cache(_RELATION_PAIR_CACHE).set_many(relation_pair_payloads)
    if caches.relation_pair_enabled and group_cache_key:
        caches.cache(_RELATION_PAIR_GROUP_CACHE).set(
            group_cache_key,
            tuple(relation_summary_from_pair(pair) for pair in result),
        )
    return result


def cached_tree_comparison_provider(
    caches: AnalysisCacheContext,
    stats: dict[str, int],
) -> Callable[[MemberFeatures, MemberFeatures], TreeComparison]:
    def compare(left: MemberFeatures, right: MemberFeatures) -> TreeComparison:
        if not caches.relation_pair_enabled:
            return tree_comparison_features(left, right)
        cache_key = tree_comparison_cache_key(left, right)
        tree = caches.cache(_TREE_COMPARISON_CACHE).get(cache_key)
        if tree is not None:
            increment_stat(stats, "tree_comparison_cache_hit_count")
            return tree
        increment_stat(stats, "tree_comparison_cache_miss_count")
        tree = tree_comparison_features(left, right)
        caches.cache(_TREE_COMPARISON_CACHE).set(cache_key, tree)
        return tree

    return compare


def relation_pair_from_cache_value(cached: object) -> tuple[bool, RelationPair | None]:
    if cached is None:
        return False, None
    if isinstance(cached, bytes):
        try:
            cached = load_cache_blob(cached)
        except Exception:
            return False, None
    if not isinstance(cached, dict):
        return False, None
    if cached.get("schema_version") != RELATION_PAIR_CACHE_VALUE_VERSION:
        return False, None
    pair = _cached_relation_pair(cached)
    if pair is None or isinstance(pair, RelationPair):
        return True, pair
    return False, None


def relation_pairs_from_group_cache_value(
    cached: object,
    feature_by_cache_key: dict[str, tuple[MemberFeatures, MemberFeatures]],
) -> tuple[bool, tuple[RelationPair, ...]]:
    cached_summaries, summaries = relation_summaries_from_group_cache_value(cached)
    if not cached_summaries:
        return False, ()
    pairs = relation_pairs_from_summaries(summaries, feature_by_cache_key)
    return (pairs is not None, pairs or ())


def relation_summaries_from_group_cache_value(
    cached: object,
) -> tuple[bool, tuple[CachedRelationSummary, ...]]:
    if cached is None:
        return False, ()
    if isinstance(cached, bytes):
        try:
            cached = load_cache_blob(cached)
        except Exception:
            return False, ()
    if (
        not isinstance(cached, dict)
        or cached.get("schema_version") != RELATION_PAIR_GROUP_CACHE_VALUE_VERSION
        or cached.get("result") != "relation_summaries"
    ):
        return False, ()
    summaries = cached.get("pairs")
    if isinstance(summaries, tuple) and all(
        isinstance(summary, CachedRelationSummary) for summary in summaries
    ):
        return True, summaries
    return False, ()


def relation_pairs_from_summaries(
    summaries: Sequence[CachedRelationSummary],
    feature_by_cache_key: dict[str, tuple[MemberFeatures, MemberFeatures]],
) -> tuple[RelationPair, ...] | None:
    pair_items = [
        relation_pair_from_summary(
            summary,
            feature_by_cache_key,
        )
        for summary in summaries
    ]
    if all(pair is not None for pair in pair_items):
        return tuple(pair for pair in pair_items if pair is not None)
    return None


_CACHE_MISS = object()


def _cached_relation_pair(cached: dict[str, object]) -> RelationPair | None | object:
    if cached.get("result") == "no_relation":
        return None
    if cached.get("result") == "relation_pair":
        pair = cached.get("pair")
        if isinstance(pair, RelationPair):
            return pair
        if isinstance(pair, dict):
            return relation_pair_from_payload(pair)
    if cached.get("schema_version") == "codeseam.structural_relation_pair.v1":
        return relation_pair_from_payload(cached)
    return _CACHE_MISS


def relation_pair_cache_key(left: MemberFeatures, right: MemberFeatures) -> str:
    return "\x1f".join(
        (
            RELATION_PAIR_CACHE_KEY_SCHEMA,
            RELATION_PAIR_CACHE_VERSION,
            left.member.digest,
            right.member.digest,
        )
    )


def tree_comparison_cache_key(left: MemberFeatures, right: MemberFeatures) -> str:
    left_key, right_key = sorted(
        (
            _tree_comparison_member_cache_key(left),
            _tree_comparison_member_cache_key(right),
        )
    )
    return "\x1f".join(
        (
            TREE_COMPARISON_CACHE_KEY_SCHEMA,
            TREE_COMPARISON_CACHE_VERSION,
            left_key,
            right_key,
        )
    )


def tree_comparison_cache_value(
    tree: TreeComparison,
) -> tuple[
    str,
    float,
    float,
    int | None,
    int,
    str,
]:
    return (
        TREE_COMPARISON_CACHE_VALUE_VERSION,
        tree.tree_similarity,
        tree.tree_distance,
        tree.tree_edit_distance,
        tree.tree_node_count,
        tree.tree_distance_source,
    )


def tree_comparison_from_cache_value(cached: object) -> tuple[bool, TreeComparison]:
    if (
        isinstance(cached, tuple)
        and len(cached) == TREE_COMPARISON_CACHE_VALUE_LENGTH
        and cached[0] == TREE_COMPARISON_CACHE_VALUE_VERSION
        and isinstance(cached[1], (int, float))
        and isinstance(cached[2], (int, float))
        and (cached[3] is None or isinstance(cached[3], int))
        and isinstance(cached[4], int)
        and isinstance(cached[5], str)
    ):
        return True, TreeComparison(
            tree_similarity=float(cached[1]),
            tree_distance=float(cached[2]),
            tree_edit_distance=cached[3],
            tree_node_count=cached[4],
            tree_distance_source=cached[5],
        )
    return False, TreeComparison(0.0, 1.0, None, 0, "unavailable")


def _tree_comparison_member_cache_key(features: MemberFeatures) -> str:
    body_hash = features.member.body_shape_hash or sha256_text(
        features.body_shape,
        errors="surrogatepass",
    )
    return "\x1e".join(
        (
            features.member.language,
            body_hash,
            str(features.tree_node_count),
        )
    )


def relation_pair_group_cache_key(cache_keys: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for cache_key in cache_keys:
        digest.update(cache_key.encode())
        digest.update(b"\0")
    return "\x1f".join(
        (
            RELATION_PAIR_GROUP_CACHE_KEY_SCHEMA,
            RELATION_PAIR_GROUP_CACHE_VERSION,
            str(len(cache_keys)),
            digest.hexdigest(),
        )
    )


def relation_pair_ref_cache_key(left: MemberRef, right: MemberRef) -> str:
    return "\x1f".join(
        (
            RELATION_PAIR_REF_CACHE_KEY_SCHEMA,
            left.signature_id,
            left.function_id,
            left.file,
            str(left.start_line),
            right.signature_id,
            right.function_id,
            right.file,
            str(right.start_line),
        )
    )


def relation_pair_cache_value(pair: RelationPair | None) -> dict[str, object]:
    if pair is None:
        return {
            "schema_version": RELATION_PAIR_CACHE_VALUE_VERSION,
            "result": "no_relation",
        }
    return {
        "schema_version": RELATION_PAIR_CACHE_VALUE_VERSION,
        "result": "relation_pair",
        "pair": pair,
    }


def relation_pair_group_cache_value(pairs: Sequence[RelationPair]) -> dict[str, object]:
    return relation_pair_group_cache_value_from_summaries(
        tuple(relation_summary_from_pair(pair) for pair in pairs)
    )


def relation_pair_group_cache_value_from_summaries(
    summaries: Sequence[CachedRelationSummary],
) -> dict[str, object]:
    return {
        "schema_version": RELATION_PAIR_GROUP_CACHE_VALUE_VERSION,
        "result": "relation_summaries",
        "pairs": tuple(summaries),
    }


def relation_summary_from_pair(pair: RelationPair) -> CachedRelationSummary:
    return CachedRelationSummary(
        cache_key=relation_pair_ref_cache_key(pair.left, pair.right),
        scores=pair.scores,
        tree=pair.tree,
        sequence=pair.sequence,
        flags=pair.flags,
        normalization=pair.relation_basis.argument_normalization,
        anti_unification=pair.anti_unification_summary,
        relation_kind=pair.relation_kind,
        relation_kinds=pair.relation_kinds,
        clone_family=pair.clone_family,
        clone_type=pair.clone_type,
        recommended_action=pair.recommended_action,
        refactorability_kind=pair.refactorability_kind,
        delta_kinds=pair.delta_kinds,
        same_role=pair.same_role,
        role=pair.role,
        max_body_line_count=pair.max_body_line_count,
        min_body_line_count=pair.min_body_line_count,
        refactor_action_candidates=pair.refactor_action_candidates,
    )


def relation_pair_from_summary(
    summary: CachedRelationSummary,
    feature_by_cache_key: dict[str, tuple[MemberFeatures, MemberFeatures]],
) -> RelationPair | None:
    features = feature_by_cache_key.get(summary.cache_key)
    if features is None:
        return None
    left_features, right_features = features
    min_body_line_count = _summary_min_body_line_count(summary) or min(
        left_features.body_line_count,
        right_features.body_line_count,
    )
    refactor_action_candidates = getattr(summary, "refactor_action_candidates", ())
    left_ref = feature_member_ref(left_features)
    right_ref = feature_member_ref(right_features)
    return RelationPair(
        left=left_ref,
        right=right_ref,
        scores=summary.scores,
        tree=summary.tree,
        sequence=summary.sequence,
        refactorability_components=RefactorabilityComponents(),
        abstraction_cost_components=AbstractionCostComponents(),
        relation_kind=summary.relation_kind,
        relation_basis=RelationBasis(
            flags=summary.flags,
            argument_normalization=summary.normalization,
            shared_prefix_length=summary.sequence.common_prefix_length,
            shared_suffix_length=summary.sequence.common_suffix_length,
            lcs_length=summary.sequence.lcs_length,
        ),
        flags=summary.flags,
        relation_kinds=summary.relation_kinds,
        clone_family=summary.clone_family,
        clone_type=summary.clone_type,
        recommended_action=summary.recommended_action,
        clone_classification=CloneClassification(
            clone_type=summary.clone_type,
            syntactic_strength="",
            default_action=summary.recommended_action,
            basis=(),
        ),
        refactorability_kind=summary.refactorability_kind,
        delta_kinds=summary.delta_kinds,
        anti_unification=SequenceSkeleton(
            template=(),
            hole_bindings={},
            stable_statement_count=summary.anti_unification.stable_statement_count,
            stable_node_ratio=summary.anti_unification.stable_node_ratio,
            common_prefix_length=summary.anti_unification.common_prefix_length,
            common_suffix_length=summary.anti_unification.common_suffix_length,
            common_prefix_ratio=summary.anti_unification.common_prefix_ratio,
            hole_count=summary.anti_unification.hole_count,
            max_hole_size=summary.anti_unification.max_hole_size,
            hole_size_variance=summary.anti_unification.hole_size_variance,
            shared_param_flow_through_holes=(
                summary.anti_unification.shared_param_flow_through_holes
            ),
        ),
        anti_unification_summary=summary.anti_unification,
        refactor_action_candidates=refactor_action_candidates,
        same_role=summary.same_role,
        role=summary.role,
        max_body_line_count=summary.max_body_line_count,
        min_body_line_count=min_body_line_count,
        refactor_shape=None,
    )


def _summary_min_body_line_count(summary: CachedRelationSummary) -> int:
    value = getattr(summary, "min_body_line_count", 0)
    return value if type(value) is int else 0
