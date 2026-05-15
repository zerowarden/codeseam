from __future__ import annotations

from codeseam.cache import relations as relation_cache
from codeseam.cache.blobs import cache_blob, load_cache_blob
from codeseam.cache.context import (
    AnalysisCacheContext,
    LanguageRunCache,
)
from codeseam.cache.file_analysis import (
    FileAnalysisCacheRequest,
    FileAnalysisCacheResult,
    FileSignatureCacheRequest,
    PrefetchedSignatures,
    cached_file_analysis,
    prefetch_cached_signatures,
    store_file_analysis,
)
from codeseam.cache.keys import (
    cache_key,
    file_analysis_cache_key,
    language_analysis_cache_key,
    repository_facts_cache_key,
)
from codeseam.cache.main import Cache, CacheCodec, CacheWriteBuffer
from codeseam.cache.relation_detail import (
    RELATION_DETAIL_FEATURE_CACHE_NAMESPACE,
    cached_relation_detail_feature_map,
    cached_relation_detail_features,
    relation_detail_cache_key,
    relation_detail_identity,
    store_relation_detail_feature_map,
    store_relation_detail_features,
)
from codeseam.cache.relations import (
    cached_relation_pair_builder,
    cached_relation_pairs,
    cached_tree_comparison_provider,
    relation_pair_cache_key,
    relation_pair_group_cache_value,
    relation_pair_ref_cache_key,
    relation_pairs_from_group_cache_value,
    tree_comparison_features,
)
from codeseam.cache.repository import (
    REPOSITORY_FACTS_CACHE_NAMESPACE,
    cached_repository_facts,
    store_repository_facts,
)
from codeseam.cache.semantic_enrichment import (
    SEMANTIC_ENRICHMENT_CACHE_NAMESPACE,
    SEMANTIC_NEGATIVE_CACHE_HIT,
    CachedSemanticProvider,
    SemanticEnrichmentCacheValue,
    semantic_enrichment_cache_key,
)
from codeseam.cache.signatures import (
    SIGNATURE_CORE_CACHE_RECORD_SCHEMA,
    SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA,
    SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA,
    signature_analyses_from_cache_values,
    signature_analyses_from_records,
    signature_core_cache_payload,
    signature_cores_from_cache_value,
    signature_features_cache_payload,
    signature_features_from_cache_value,
    signature_output_cache_payload,
    signature_output_from_cache_value,
)
from codeseam.cache.stats import cache_stats
from codeseam.cache.store import PersistentCache, persistent_cache
from codeseam.version import CACHE_BUSY_TIMEOUT_MS, CACHE_DB, CACHE_TIMEOUT_SECONDS

__all__ = [
    "CACHE_DB",
    "CACHE_BUSY_TIMEOUT_MS",
    "CACHE_TIMEOUT_SECONDS",
    "AnalysisCacheContext",
    "Cache",
    "CacheCodec",
    "CacheWriteBuffer",
    "CachedSemanticProvider",
    "FileAnalysisCacheRequest",
    "FileAnalysisCacheResult",
    "FileSignatureCacheRequest",
    "LanguageRunCache",
    "PersistentCache",
    "PrefetchedSignatures",
    "RELATION_DETAIL_FEATURE_CACHE_NAMESPACE",
    "REPOSITORY_FACTS_CACHE_NAMESPACE",
    "SEMANTIC_ENRICHMENT_CACHE_NAMESPACE",
    "SEMANTIC_NEGATIVE_CACHE_HIT",
    "SIGNATURE_CORE_CACHE_RECORD_SCHEMA",
    "SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA",
    "SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA",
    "SemanticEnrichmentCacheValue",
    "cached_file_analysis",
    "cached_relation_detail_feature_map",
    "cached_relation_detail_features",
    "cached_relation_pair_builder",
    "cached_relation_pairs",
    "cached_repository_facts",
    "cached_tree_comparison_provider",
    "cache_blob",
    "cache_key",
    "cache_stats",
    "file_analysis_cache_key",
    "language_analysis_cache_key",
    "load_cache_blob",
    "persistent_cache",
    "prefetch_cached_signatures",
    "relation_detail_cache_key",
    "relation_detail_identity",
    "repository_facts_cache_key",
    "relation_cache",
    "relation_pair_cache_key",
    "relation_pair_group_cache_value",
    "relation_pair_ref_cache_key",
    "relation_pairs_from_group_cache_value",
    "signature_analyses_from_cache_values",
    "signature_analyses_from_records",
    "signature_core_cache_payload",
    "signature_cores_from_cache_value",
    "signature_features_cache_payload",
    "signature_features_from_cache_value",
    "signature_output_cache_payload",
    "signature_output_from_cache_value",
    "store_relation_detail_feature_map",
    "store_relation_detail_features",
    "store_file_analysis",
    "store_repository_facts",
    "semantic_enrichment_cache_key",
    "tree_comparison_features",
]
