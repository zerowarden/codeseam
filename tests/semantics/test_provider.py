from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.cache import (
    SEMANTIC_ENRICHMENT_CACHE_NAMESPACE,
    SEMANTIC_NEGATIVE_CACHE_HIT,
    CachedSemanticProvider,
    SemanticEnrichmentCacheValue,
    cache_blob,
    persistent_cache,
    semantic_enrichment_cache_key,
)
from codeseam.semantics import (
    SemanticBudget,
    SemanticEnrichedItem,
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProjectSummary,
    SemanticProviderMetadata,
    SemanticProviderRequiredError,
    SemanticProviderStatus,
    run_semantic_enrichment,
)

EXPECTED_PROVIDER_CALLS = 2


def test_semantics_off_does_not_instantiate_or_call_provider() -> None:
    provider = _CountingProvider()

    run = run_semantic_enrichment(
        (_request(),),
        mode=SemanticMode.OFF,
        provider=provider,
    )

    assert run.status is SemanticProviderStatus.DISABLED
    assert run.requests == ()
    assert run.results == ()
    assert provider.calls == 0


def test_auto_without_provider_falls_back_for_candidate_requests() -> None:
    request = _request()

    run = run_semantic_enrichment((request,), mode=SemanticMode.AUTO)

    assert run.status is SemanticProviderStatus.UNAVAILABLE
    assert run.results[0].fallback == "tree_sitter_only"
    assert "semantic_provider_unavailable" in run.caveats


def test_required_without_provider_fails_when_candidates_exist() -> None:
    with pytest.raises(SemanticProviderRequiredError, match="provider unavailable"):
        run_semantic_enrichment((_request(),), mode=SemanticMode.REQUIRED)


def test_required_without_candidates_does_not_need_provider() -> None:
    run = run_semantic_enrichment((), mode=SemanticMode.REQUIRED)

    assert run.status is SemanticProviderStatus.DISABLED
    assert run.results == ()
    assert "no_semantic_candidates" in run.caveats


def test_provider_is_called_once_per_request() -> None:
    provider = _CountingProvider()

    run = run_semantic_enrichment(
        (_request("request-1"), _request("request-2")),
        mode=SemanticMode.PROJECT,
        provider=provider,
        budget=SemanticBudget(request_timeout_ms=10),
    )

    assert run.status is SemanticProviderStatus.READY
    assert provider.calls == EXPECTED_PROVIDER_CALLS
    assert [result.request_id for result in run.results] == ["request-1", "request-2"]


def test_cached_provider_reuses_persistent_ready_result(tmp_path: Path) -> None:
    request = _request()
    budget = SemanticBudget(request_timeout_ms=10)
    cache_root = tmp_path / ".cache"

    first_cache = persistent_cache(cache_root, enabled=True)
    first_provider = _CountingProvider()
    first = CachedSemanticProvider(first_provider, first_cache).enrich(request, budget)
    first_cache.close()

    second_cache = persistent_cache(cache_root, enabled=True)
    second_provider = _CountingProvider()
    second = CachedSemanticProvider(second_provider, second_cache).enrich(request, budget)
    second_cache.close()

    assert first.status is SemanticProviderStatus.READY
    assert second.status is SemanticProviderStatus.READY
    assert first_provider.calls == 1
    assert second_provider.calls == 0
    assert second.items == first.items


def test_cached_provider_ignores_corrupt_semantic_blob(tmp_path: Path) -> None:
    request = _request()
    budget = SemanticBudget(request_timeout_ms=10)
    cache = persistent_cache(tmp_path / ".cache", enabled=True)
    key = semantic_enrichment_cache_key(request, budget)
    cache.set_blob(SEMANTIC_ENRICHMENT_CACHE_NAMESPACE, key, b"not-a-cache-blob")
    provider = _CountingProvider()

    result = CachedSemanticProvider(provider, cache).enrich(request, budget)
    cache.close()

    assert result.status is SemanticProviderStatus.READY
    assert provider.calls == 1


def test_cached_provider_invalidates_stale_semantic_schema(tmp_path: Path) -> None:
    request = _request()
    budget = SemanticBudget(request_timeout_ms=10)
    cache = persistent_cache(tmp_path / ".cache", enabled=True)
    key = semantic_enrichment_cache_key(request, budget)
    cache.set_blob(
        SEMANTIC_ENRICHMENT_CACHE_NAMESPACE,
        key,
        cache_blob(
            SemanticEnrichmentCacheValue(
                schema_version="old",
                fingerprint=key,
                result=_ready_result(request),
            )
        ),
    )
    provider = _CountingProvider()

    result = CachedSemanticProvider(provider, cache).enrich(request, budget)
    cache.close()

    assert result.status is SemanticProviderStatus.READY
    assert provider.calls == 1


def test_cached_provider_negative_cache_is_in_memory_only(tmp_path: Path) -> None:
    request = _request()
    budget = SemanticBudget(request_timeout_ms=10)
    cache = persistent_cache(tmp_path / ".cache", enabled=True)
    provider = _CountingProvider(status=SemanticProviderStatus.TIMED_OUT)
    cached = CachedSemanticProvider(provider, cache)

    first = cached.enrich(request, budget)
    second = cached.enrich(request, budget)
    cache.close()

    reopened = persistent_cache(tmp_path / ".cache", enabled=True)
    retry_provider = _CountingProvider(status=SemanticProviderStatus.TIMED_OUT)
    retry = CachedSemanticProvider(retry_provider, reopened).enrich(request, budget)
    reopened.close()

    assert first.status is SemanticProviderStatus.TIMED_OUT
    assert second.status is SemanticProviderStatus.TIMED_OUT
    assert SEMANTIC_NEGATIVE_CACHE_HIT in second.caveats
    assert provider.calls == 1
    assert retry_provider.calls == 1
    assert retry.status is SemanticProviderStatus.TIMED_OUT


def test_semantic_cache_key_changes_when_project_key_changes() -> None:
    budget = SemanticBudget(request_timeout_ms=10)
    left = semantic_enrichment_cache_key(_request(project_cache_key="sha256:left"), budget)
    right = semantic_enrichment_cache_key(_request(project_cache_key="sha256:right"), budget)

    assert left != right


class _CountingProvider:
    def __init__(self, *, status: SemanticProviderStatus = SemanticProviderStatus.READY) -> None:
        self.calls = 0
        self.status = status

    def enrich(
        self,
        request: SemanticEnrichmentRequest,
        budget: SemanticBudget,
    ) -> SemanticEnrichmentResult:
        self.calls += 1
        assert budget.request_timeout_ms > 0
        if self.status != SemanticProviderStatus.READY:
            return SemanticEnrichmentResult.unavailable(
                request,
                status=self.status,
                reason="counting_provider_unavailable",
            )
        return _ready_result(request)


def run_project_summary(request: SemanticEnrichmentRequest) -> SemanticProjectSummary:
    return SemanticProjectSummary(
        project_cache_key=request.project_cache_key,
        config_path=request.config_path,
    )


def _ready_result(request: SemanticEnrichmentRequest) -> SemanticEnrichmentResult:
    return SemanticEnrichmentResult(
        request_id=request.request_id,
        language=request.language,
        mode=request.mode,
        status=SemanticProviderStatus.READY,
        provider=SemanticProviderMetadata(
            name="counting_provider",
            mode=request.mode,
        ),
        project=run_project_summary(request),
        items=(
            SemanticEnrichedItem(
                signature_id="sig_1",
                resolved=True,
                return_type="number",
            ),
        ),
    )


def _request(
    request_id: str = "request-1",
    *,
    project_cache_key: str = "sha256:project",
) -> SemanticEnrichmentRequest:
    return SemanticEnrichmentRequest(
        request_id=request_id,
        language="TypeScript",
        mode=SemanticMode.AUTO,
        repo_root="/repo",
        project_cache_key=project_cache_key,
        config_path="/repo/tsconfig.json",
        items=(
            SemanticEnrichmentItem(
                signature_id="sig_1",
                relative_path="src/index.ts",
                start_line=1,
                end_line=3,
                callable_kind="function",
                symbol_hint="run",
            ),
        ),
    )
