from __future__ import annotations

from dataclasses import dataclass, field, replace

from codeseam.cache.keys import cache_key
from codeseam.cache.main import Cache, CacheCodec
from codeseam.cache.store import PersistentCache
from codeseam.semantics.enrichment import (
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticProviderStatus,
)
from codeseam.semantics.provider import SemanticBudget, SemanticProvider
from codeseam.version import (
    SEMANTIC_ENRICHMENT_CACHE_KEY_SCHEMA,
    SEMANTIC_ENRICHMENT_CACHE_VALUE_VERSION,
)

SEMANTIC_ENRICHMENT_CACHE_NAMESPACE = "semantic_enrichment"
SEMANTIC_NEGATIVE_CACHE_HIT = "semantic_negative_cache_hit"


@dataclass(frozen=True, slots=True)
class SemanticEnrichmentCacheValue:
    """Typed persistent cache value for normalized semantic worker output.

    The cache stores only Codeseam-owned enrichment models. It deliberately does
    not store TypeScript ASTs, Programs, raw source, diagnostics, or worker JSON.
    """

    schema_version: str
    fingerprint: str
    result: SemanticEnrichmentResult


@dataclass(frozen=True, slots=True)
class _SemanticEnrichmentCacheCodec(CacheCodec[SemanticEnrichmentCacheValue]):
    namespace: str

    def dump(self, value: SemanticEnrichmentCacheValue) -> object:
        return value

    def load(self, value: object) -> SemanticEnrichmentCacheValue | None:
        if not isinstance(value, SemanticEnrichmentCacheValue):
            return None
        if value.schema_version != SEMANTIC_ENRICHMENT_CACHE_VALUE_VERSION:
            return None
        return value


@dataclass(slots=True)
class CachedSemanticProvider:
    """Cache wrapper for expensive semantic provider calls.

    Persistent hits avoid spawning/loading an external worker at all. Non-ready
    results are kept only in memory for the current run, which prevents repeated
    timeouts while avoiding stale failure state across future analyses.
    """

    provider: SemanticProvider
    cache: PersistentCache
    namespace: str = SEMANTIC_ENRICHMENT_CACHE_NAMESPACE
    _negative: dict[str, SemanticEnrichmentResult] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._negative = {}

    def enrich(
        self,
        request: SemanticEnrichmentRequest,
        budget: SemanticBudget,
    ) -> SemanticEnrichmentResult:
        return self.enrich_many((request,), budget)[0]

    def enrich_many(
        self,
        requests: tuple[SemanticEnrichmentRequest, ...],
        budget: SemanticBudget,
    ) -> tuple[SemanticEnrichmentResult, ...]:
        fingerprints = {
            request.request_id: semantic_enrichment_cache_key(request, budget)
            for request in requests
        }
        results_by_request_id: dict[str, SemanticEnrichmentResult] = {}
        persistent_candidates: list[SemanticEnrichmentRequest] = []
        for request in requests:
            fingerprint = fingerprints[request.request_id]
            if fingerprint in self._negative:
                results_by_request_id[request.request_id] = _for_request(
                    self._negative[fingerprint],
                    request,
                    extra_caveat=SEMANTIC_NEGATIVE_CACHE_HIT,
                )
            else:
                persistent_candidates.append(request)

        semantic_cache: Cache[SemanticEnrichmentCacheValue] = Cache(
            self.cache,
            _SemanticEnrichmentCacheCodec(self.namespace),
        )
        cached_values = semantic_cache.get_many(
            tuple(fingerprints[request.request_id] for request in persistent_candidates)
        )
        misses: list[SemanticEnrichmentRequest] = []
        for request in persistent_candidates:
            fingerprint = fingerprints[request.request_id]
            cached = _cached_result_from_value(
                cached_values.get(fingerprint),
                fingerprint,
                request,
            )
            if cached is None:
                misses.append(request)
            else:
                results_by_request_id[request.request_id] = cached

        writes: dict[str, SemanticEnrichmentCacheValue] = {}
        for request in misses:
            fingerprint = fingerprints[request.request_id]
            result = self.provider.enrich(request, budget)
            if result.status == SemanticProviderStatus.READY:
                writes[fingerprint] = SemanticEnrichmentCacheValue(
                    schema_version=SEMANTIC_ENRICHMENT_CACHE_VALUE_VERSION,
                    fingerprint=fingerprint,
                    result=result,
                )
            else:
                self._negative[fingerprint] = result
            results_by_request_id[request.request_id] = result
        if writes:
            semantic_cache.set_many(writes)
        return tuple(results_by_request_id[request.request_id] for request in requests)


def semantic_enrichment_cache_key(
    request: SemanticEnrichmentRequest,
    budget: SemanticBudget,
) -> str:
    """Return a deterministic fingerprint for one semantic enrichment request."""

    return cache_key(
        {
            "schema_version": SEMANTIC_ENRICHMENT_CACHE_KEY_SCHEMA,
            "language": request.language,
            "mode": request.mode,
            "repo_root": request.repo_root,
            "project_cache_key": request.project_cache_key,
            "config_path": request.config_path,
            "budget": _budget_key(budget),
            "items": [_item_key(item) for item in request.items],
        }
    )


def _cached_result_from_value(
    value: SemanticEnrichmentCacheValue | None,
    fingerprint: str,
    request: SemanticEnrichmentRequest,
) -> SemanticEnrichmentResult | None:
    if value is None:
        return None
    if value.fingerprint != fingerprint or value.result.status != SemanticProviderStatus.READY:
        return None
    return _for_request(value.result, request)


def _for_request(
    result: SemanticEnrichmentResult,
    request: SemanticEnrichmentRequest,
    *,
    extra_caveat: str = "",
) -> SemanticEnrichmentResult:
    caveats = result.caveats
    if extra_caveat and extra_caveat not in caveats:
        caveats = (*caveats, extra_caveat)
    return replace(
        result,
        request_id=request.request_id,
        language=request.language,
        mode=request.mode,
        caveats=caveats,
    )


def _item_key(item: SemanticEnrichmentItem) -> tuple[object, ...]:
    return (
        item.signature_id,
        item.relative_path,
        item.start_line,
        item.end_line,
        item.callable_kind,
        item.symbol_hint,
        item.start_byte,
        item.end_byte,
    )


def _budget_key(budget: SemanticBudget) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            {
                "startup_timeout_ms": budget.startup_timeout_ms,
                "project_load_timeout_ms": budget.project_load_timeout_ms,
                "request_timeout_ms": budget.request_timeout_ms,
                "max_items_per_batch": budget.max_items_per_batch,
                "max_type_text_chars": budget.max_type_text_chars,
            }.items()
        )
    )


__all__ = [
    "SEMANTIC_ENRICHMENT_CACHE_NAMESPACE",
    "SEMANTIC_NEGATIVE_CACHE_HIT",
    "CachedSemanticProvider",
    "SemanticEnrichmentCacheValue",
    "semantic_enrichment_cache_key",
]
