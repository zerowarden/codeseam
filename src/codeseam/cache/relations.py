from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from codeseam.analysis import (
    PAIR_POLICY,
    ActionBuilder,
    MemberFeatureCache,
    MemberFeatures,
    MemberInput,
    RelationPair,
    RelationPairBuilder,
    TreeComparison,
    relation_pair_from_features,
    tree_comparison_features,
)
from codeseam.cache.blobs import load_cache_blob
from codeseam.cache.context import AnalysisCacheContext
from codeseam.cache.main import CacheCodec
from codeseam.platform import increment_stat, sha256_text
from codeseam.version import (
    RELATION_PAIR_CACHE_KEY_SCHEMA,
    RELATION_PAIR_CACHE_VALUE_VERSION,
    RELATION_PAIR_CACHE_VERSION,
    TREE_COMPARISON_CACHE_KEY_SCHEMA,
    TREE_COMPARISON_CACHE_VALUE_VERSION,
    TREE_COMPARISON_CACHE_VERSION,
)

RELATION_PAIR_CACHE_NAMESPACE = "relation_pairs"
TREE_COMPARISON_CACHE_NAMESPACE = "tree_comparisons"
TREE_COMPARISON_CACHE_VALUE_LENGTH = 6

__all__ = [
    "cached_relation_pair_builder",
    "cached_relation_pairs",
    "cached_tree_comparison_provider",
    "relation_pair_cache_key",
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
class _TreeComparisonCacheCodec(CacheCodec[TreeComparison]):
    namespace: str = TREE_COMPARISON_CACHE_NAMESPACE

    def dump(self, value: TreeComparison) -> object:
        return tree_comparison_cache_value(value)

    def load(self, value: object) -> TreeComparison | None:
        cached, tree = tree_comparison_from_cache_value(value)
        return tree if cached else None


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
    ) -> list[RelationPair]:
        return cached_relation_pairs(
            candidate_pairs,
            action_builder=action_builder,
            feature_cache=feature_cache,
            stats=stats,
            caches=caches,
        )

    return build


def cached_relation_pairs(  # noqa: PLR0913
    candidate_pairs: Sequence[tuple[MemberInput, MemberInput]],
    *,
    action_builder: ActionBuilder,
    feature_cache: MemberFeatureCache,
    stats: dict[str, int],
    caches: AnalysisCacheContext,
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


_CACHE_MISS = object()


def _cached_relation_pair(cached: dict[str, object]) -> RelationPair | None | object:
    if cached.get("result") == "no_relation":
        return None
    if cached.get("result") == "relation_pair":
        pair = cached.get("pair")
        if isinstance(pair, RelationPair):
            return pair
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
