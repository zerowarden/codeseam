from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from codeseam.analysis import (
    FileRecord,
    FunctionRecord,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
)
from codeseam.cache.keys import cache_key
from codeseam.cache.main import Cache, CacheCodec
from codeseam.cache.store import PersistentCache
from codeseam.version import (
    RELATION_DETAIL_CACHE_KEY_SCHEMA,
    RELATION_DETAIL_CACHE_VALUE_VERSION,
)

RELATION_DETAIL_FEATURE_CACHE_NAMESPACE = "relation_detail_features"
RELATION_DETAIL_CACHE_VALUE_LENGTH = 2

type RelationDetailFeatureCacheValue = tuple[str, SignatureAnalysisFeatures]


@dataclass(frozen=True, slots=True)
class RelationDetailFeatureCacheIdentity:
    adapter_id: str
    language: str
    file: str
    file_content_hash: str
    symbol: str
    start_line: int
    end_line: int
    function_content_hash: str


@dataclass(frozen=True, slots=True)
class _RelationDetailFeatureCacheCodec(CacheCodec[SignatureAnalysisFeatures]):
    namespace: str = RELATION_DETAIL_FEATURE_CACHE_NAMESPACE

    def dump(self, value: SignatureAnalysisFeatures) -> object:
        return relation_detail_cache_value(value)

    def load(self, value: object) -> SignatureAnalysisFeatures | None:
        return relation_detail_features_from_cache_value(value)


_RELATION_DETAIL_FEATURE_CACHE = _RelationDetailFeatureCacheCodec()


def relation_detail_cache_key(identity: RelationDetailFeatureCacheIdentity) -> str:
    return cache_key(
        {
            "schema_version": RELATION_DETAIL_CACHE_KEY_SCHEMA,
            "adapter_id": identity.adapter_id,
            "language": identity.language,
            "file": identity.file,
            "file_content_hash": identity.file_content_hash,
            "symbol": identity.symbol,
            "start_line": identity.start_line,
            "end_line": identity.end_line,
            "function_content_hash": identity.function_content_hash,
        }
    )


def relation_detail_identity(
    signature: SignatureAnalysis,
    *,
    file_record: FileRecord,
    function: FunctionRecord,
    adapter_id: str,
) -> RelationDetailFeatureCacheIdentity:
    core = signature.core
    return RelationDetailFeatureCacheIdentity(
        adapter_id=adapter_id,
        language=core.language,
        file=core.file,
        file_content_hash=file_record.content_hash,
        symbol=core.symbol,
        start_line=core.start_line,
        end_line=core.end_line,
        function_content_hash=function.content_hash,
    )


def cached_relation_detail_features(
    cache: PersistentCache,
    key: str,
    *,
    signature_id: str,
) -> SignatureAnalysisFeatures | None:
    feature_cache = Cache[SignatureAnalysisFeatures](cache, _RELATION_DETAIL_FEATURE_CACHE)
    features = feature_cache.get(key)
    if features is None:
        return None
    return replace(features, signature_id=signature_id)


def cached_relation_detail_feature_map(
    cache: PersistentCache,
    keys_by_signature_id: Mapping[str, str],
) -> dict[str, SignatureAnalysisFeatures]:
    feature_cache = Cache[SignatureAnalysisFeatures](cache, _RELATION_DETAIL_FEATURE_CACHE)
    cached: dict[str, SignatureAnalysisFeatures] = feature_cache.get_many(
        tuple(keys_by_signature_id.values())
    )
    features_by_signature_id: dict[str, SignatureAnalysisFeatures] = {}
    for signature_id, key in keys_by_signature_id.items():
        features = cached.get(key)
        if features is not None:
            features_by_signature_id[signature_id] = replace(
                features,
                signature_id=signature_id,
            )
    return features_by_signature_id


def store_relation_detail_features(
    cache: PersistentCache,
    key: str,
    features: SignatureAnalysisFeatures,
) -> None:
    feature_cache = Cache[SignatureAnalysisFeatures](cache, _RELATION_DETAIL_FEATURE_CACHE)
    feature_cache.set(key, features)


def store_relation_detail_feature_map(
    cache: PersistentCache,
    features_by_key: Mapping[str, SignatureAnalysisFeatures],
) -> None:
    feature_cache = Cache[SignatureAnalysisFeatures](cache, _RELATION_DETAIL_FEATURE_CACHE)
    feature_cache.set_many(features_by_key)


def relation_detail_cache_value(
    features: SignatureAnalysisFeatures,
) -> RelationDetailFeatureCacheValue:
    return (RELATION_DETAIL_CACHE_VALUE_VERSION, features)


def relation_detail_features_from_cache_value(
    value: object,
) -> SignatureAnalysisFeatures | None:
    if not isinstance(value, tuple) or len(value) != RELATION_DETAIL_CACHE_VALUE_LENGTH:
        return None
    version, features = value
    if version != RELATION_DETAIL_CACHE_VALUE_VERSION:
        return None
    return features if isinstance(features, SignatureAnalysisFeatures) else None


__all__ = [
    "RELATION_DETAIL_FEATURE_CACHE_NAMESPACE",
    "RelationDetailFeatureCacheIdentity",
    "cached_relation_detail_feature_map",
    "cached_relation_detail_features",
    "relation_detail_cache_key",
    "relation_detail_cache_value",
    "relation_detail_features_from_cache_value",
    "relation_detail_identity",
    "store_relation_detail_feature_map",
    "store_relation_detail_features",
]
