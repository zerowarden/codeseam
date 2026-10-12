from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from codeseam.analysis import (
    CachedPair,
    FeaturePair,
    MemberFeatures,
    RelationPair,
    TreeComparison,
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
    "RelationPairStore",
    "relation_pair_store",
    "relation_pair_cache_key",
    "tree_comparison_features",
]


@dataclass(frozen=True, slots=True)
class _RelationPairCacheCodec(CacheCodec[CachedPair]):
    namespace: str = RELATION_PAIR_CACHE_NAMESPACE

    def dump(self, value: CachedPair) -> object:
        return relation_pair_cache_value(value.pair)

    def load(self, value: object) -> CachedPair | None:
        cached, pair = relation_pair_from_cache_value(value)
        return CachedPair(pair) if cached else None


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


@dataclass(frozen=True, slots=True)
class RelationPairStore:
    """`PairCache` backed by the persistent cache: stores pairs and tree comparisons."""

    caches: AnalysisCacheContext

    def get_many(self, pairs: Sequence[FeaturePair]) -> list[CachedPair | None]:
        if not self.caches.relation_pair_enabled:
            return [None] * len(pairs)
        keys = [relation_pair_cache_key(left, right) for left, right in pairs]
        found = self.caches.cache(_RELATION_PAIR_CACHE).get_many(keys)
        return [found.get(key) for key in keys]

    def set_many(self, results: Sequence[tuple[FeaturePair, RelationPair | None]]) -> None:
        if self.caches.relation_pair_enabled:
            self.caches.cache(_RELATION_PAIR_CACHE).set_many(
                {relation_pair_cache_key(*pair): CachedPair(result) for pair, result in results}
            )

    def compare_trees(
        self, left: MemberFeatures, right: MemberFeatures, stats: dict[str, int] | None
    ) -> TreeComparison:
        if not self.caches.relation_pair_enabled:
            return tree_comparison_features(left, right)
        cache_key = tree_comparison_cache_key(left, right)
        tree = self.caches.cache(_TREE_COMPARISON_CACHE).get(cache_key)
        if tree is not None:
            increment_stat(stats, "tree_comparison_cache_hit_count")
            return tree
        increment_stat(stats, "tree_comparison_cache_miss_count")
        tree = tree_comparison_features(left, right)
        self.caches.cache(_TREE_COMPARISON_CACHE).set(cache_key, tree)
        return tree


def relation_pair_store(caches: AnalysisCacheContext | None) -> RelationPairStore | None:
    return RelationPairStore(caches) if caches is not None else None


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
