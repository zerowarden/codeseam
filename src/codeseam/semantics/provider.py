from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from codeseam.semantics.enrichment import (
    SemanticEnrichmentRequest,
    SemanticEnrichmentResult,
    SemanticMode,
    SemanticProviderStatus,
)

DEFAULT_STARTUP_TIMEOUT_MS = 1_000
DEFAULT_PROJECT_LOAD_TIMEOUT_MS = 5_000
DEFAULT_REQUEST_TIMEOUT_MS = 2_000
DEFAULT_MAX_ITEMS_PER_BATCH = 200
DEFAULT_MAX_TYPE_TEXT_CHARS = 240


class SemanticProviderRequiredError(RuntimeError):
    """Raised when semantic mode requires a provider and none is available."""


@dataclass(frozen=True, slots=True)
class SemanticBudget:
    """Hard limits for optional semantic provider calls.

    The first provider stages may only return unavailable status, but the
    budget is part of the interface now so future TypeScript/Rust/Swift workers
    are forced to respect bounded execution from the start.
    """

    startup_timeout_ms: int = DEFAULT_STARTUP_TIMEOUT_MS
    project_load_timeout_ms: int = DEFAULT_PROJECT_LOAD_TIMEOUT_MS
    request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS
    max_items_per_batch: int = DEFAULT_MAX_ITEMS_PER_BATCH
    max_type_text_chars: int = DEFAULT_MAX_TYPE_TEXT_CHARS


class SemanticProvider(Protocol):
    def enrich(
        self,
        request: SemanticEnrichmentRequest,
        budget: SemanticBudget,
    ) -> SemanticEnrichmentResult: ...


@runtime_checkable
class BatchSemanticProvider(Protocol):
    def enrich_many(
        self,
        requests: tuple[SemanticEnrichmentRequest, ...],
        budget: SemanticBudget,
    ) -> tuple[SemanticEnrichmentResult, ...]: ...


@dataclass(frozen=True, slots=True)
class SemanticEnrichmentRun:
    mode: SemanticMode
    status: SemanticProviderStatus
    requests: tuple[SemanticEnrichmentRequest, ...] = ()
    results: tuple[SemanticEnrichmentResult, ...] = ()
    caveats: tuple[str, ...] = ()


def run_semantic_enrichment(
    requests: tuple[SemanticEnrichmentRequest, ...],
    *,
    mode: SemanticMode,
    provider: SemanticProvider | None = None,
    budget: SemanticBudget | None = None,
) -> SemanticEnrichmentRun:
    """Run optional semantic enrichment after candidate selection.

    `off` is a true no-op. `auto` and `project` are allowed to fall back to
    parser-only evidence when no provider exists. `required` is the only mode
    that fails when candidates need semantic facts but no provider is available.
    """

    if mode == SemanticMode.OFF:
        return SemanticEnrichmentRun(
            mode=mode,
            status=SemanticProviderStatus.DISABLED,
            caveats=("semantic_mode_off",),
        )
    if not requests:
        return SemanticEnrichmentRun(
            mode=mode,
            status=SemanticProviderStatus.DISABLED,
            caveats=("no_semantic_candidates",),
        )
    if provider is None:
        if mode == SemanticMode.REQUIRED:
            raise SemanticProviderRequiredError("semantic provider unavailable")
        results = tuple(
            SemanticEnrichmentResult.unavailable(
                request,
                status=SemanticProviderStatus.UNAVAILABLE,
                reason="semantic_provider_unavailable",
            )
            for request in requests
        )
        return SemanticEnrichmentRun(
            mode=mode,
            status=SemanticProviderStatus.UNAVAILABLE,
            requests=requests,
            results=results,
            caveats=("semantic_provider_unavailable",),
        )
    active_budget = budget or SemanticBudget()
    results = (
        provider.enrich_many(requests, active_budget)
        if isinstance(provider, BatchSemanticProvider)
        else tuple(provider.enrich(request, active_budget) for request in requests)
    )
    status = _run_status(results)
    if mode == SemanticMode.REQUIRED and status != SemanticProviderStatus.READY:
        raise SemanticProviderRequiredError(f"semantic provider required but returned {status}")
    return SemanticEnrichmentRun(
        mode=mode,
        status=status,
        requests=requests,
        results=results,
        caveats=tuple(caveat for result in results for caveat in result.caveats),
    )


def _run_status(results: tuple[SemanticEnrichmentResult, ...]) -> SemanticProviderStatus:
    if not results:
        return SemanticProviderStatus.DISABLED
    if all(result.status == SemanticProviderStatus.READY for result in results):
        return SemanticProviderStatus.READY
    if any(result.status == SemanticProviderStatus.TIMED_OUT for result in results):
        return SemanticProviderStatus.TIMED_OUT
    if any(result.status == SemanticProviderStatus.FAILED for result in results):
        return SemanticProviderStatus.FAILED
    return SemanticProviderStatus.UNAVAILABLE


__all__ = [
    "SemanticBudget",
    "SemanticEnrichmentRun",
    "BatchSemanticProvider",
    "SemanticProvider",
    "SemanticProviderRequiredError",
    "run_semantic_enrichment",
]
