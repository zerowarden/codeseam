from __future__ import annotations

from dataclasses import dataclass

from codeseam.adapters.languages import (
    AdapterCapabilitySummary,
    AdapterId,
    LanguageRegistry,
    RepositoryAdapterFact,
    default_language_registry,
    repo_facts_provider,
)
from codeseam.analysis import RepositoryFacts


@dataclass(frozen=True, slots=True)
class RepositoryEnrichment:
    """Optional adapter facts derived after cheap repository facts are known.

    This is deliberately separate from `RepositoryFacts`: repository facts are
    cheap scanner output, while enrichment is adapter-dependent and may be
    unavailable. Providers are called only when an adapter explicitly advertises
    `repo_facts`, so syntax-only adapters do not add work to the hot path.
    """

    adapter_capabilities: tuple[AdapterCapabilitySummary, ...] = ()
    adapter_facts: tuple[RepositoryAdapterFact, ...] = ()


def build_repository_enrichment(
    facts: RepositoryFacts,
    registry: LanguageRegistry | None = None,
) -> RepositoryEnrichment:
    registry = registry or default_language_registry()
    capabilities = registry.capability_summaries(facts.language_counts)
    adapter_facts: list[RepositoryAdapterFact] = []
    seen_fact_adapters: set[AdapterId] = set()
    for summary in capabilities:
        if summary.adapter_id in seen_fact_adapters:
            continue
        adapter = registry.adapter_for_language(summary.language)
        provider = repo_facts_provider(adapter)
        if provider is None:
            continue
        seen_fact_adapters.add(summary.adapter_id)
        adapter_facts.append(
            RepositoryAdapterFact(
                language=summary.language,
                adapter_id=summary.adapter_id,
                facts=provider.extract_repo_facts(facts),
            )
        )
    return RepositoryEnrichment(
        adapter_capabilities=capabilities,
        adapter_facts=tuple(adapter_facts),
    )


__all__ = ["RepositoryEnrichment", "build_repository_enrichment"]
