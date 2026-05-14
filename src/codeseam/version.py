from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_FALLBACK_VERSION = "0.1.0"


def _installed_version() -> str:
    try:
        return version("codeseam")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _installed_version()


def _cache_version(name: str) -> str:
    return f"{name}.{__version__}"


CACHE_DB = "cache.sqlite3"
CACHE_TIMEOUT_SECONDS = 30.0
CACHE_BUSY_TIMEOUT_MS = 5_000
CACHE_RUN_STATS_SCHEMA_VERSION = "codeseam.cache_run_stats.v1"
CACHE_STATS_SCHEMA_VERSION = "codeseam.cache_stats.v1"

# Internal cache versions are tied to the installed Codeseam version. They are
# intentionally concise because they are persisted inside cache keys/blobs, not
# exposed as public artifact schemas.
FILE_ANALYSIS_CACHE_VERSION = _cache_version("file_analysis")
FILE_ANALYSIS_CACHE_KEY_SCHEMA_VERSION = _cache_version("file_key")

SIGNATURE_CORE_CACHE_RECORD_SCHEMA = _cache_version("sig_core.v8")
SIGNATURE_FEATURES_CACHE_RECORD_SCHEMA = _cache_version("sig_feat.v2")
SIGNATURE_OUTPUT_CACHE_RECORD_SCHEMA = _cache_version("sig_output.v4")
FUNCTION_CACHE_RECORD_SCHEMA = _cache_version("fn_core")
POLICY_CONSTANT_CACHE_RECORD_SCHEMA = _cache_version("policy_const.v2")

REPOSITORY_FACTS_CACHE_KEY_SCHEMA = _cache_version("repo_facts_key")
REPOSITORY_FACTS_CACHE_VALUE_VERSION = _cache_version("repo_facts_value")

RELATION_PAIR_CACHE_VERSION = _cache_version("rel_pair.v2")
RELATION_PAIR_CACHE_KEY_SCHEMA = _cache_version("rel_pair_key")
RELATION_PAIR_CACHE_VALUE_VERSION = _cache_version("rel_pair_value.v2")
RELATION_PAIR_GROUP_CACHE_VERSION = _cache_version("rel_group.v2")
RELATION_PAIR_GROUP_CACHE_KEY_SCHEMA = _cache_version("rel_group_key")
RELATION_PAIR_GROUP_CACHE_VALUE_VERSION = _cache_version("rel_group_value.v2")
RELATION_PAIR_REF_CACHE_KEY_SCHEMA = _cache_version("rel_pair_ref_key")
RELATION_DETAIL_CACHE_KEY_SCHEMA = _cache_version("rel_detail_key")
RELATION_DETAIL_CACHE_VALUE_VERSION = _cache_version("rel_detail_value.v2")
TREE_COMPARISON_CACHE_VERSION = _cache_version("tree_comp")
TREE_COMPARISON_CACHE_KEY_SCHEMA = _cache_version("tree_comp_key")
TREE_COMPARISON_CACHE_VALUE_VERSION = _cache_version("tree_comp_value")

SEMANTIC_ENRICHMENT_CACHE_KEY_SCHEMA = _cache_version("semantic_enrichment_key")
SEMANTIC_ENRICHMENT_CACHE_VALUE_VERSION = _cache_version("semantic_enrichment_value")


def package_version() -> str:
    return __version__
