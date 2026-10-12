"""Build the completeness summary of one run from what the pipeline recorded."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from codeseam.adapters.languages import AdapterCapabilitySummary
from codeseam.analysis import (
    OTHER_SOURCE_LANGUAGES,
    Clusters,
    CompletenessInputs,
    CompletenessSummary,
    RepositoryFacts,
    completeness_summary,
)
from codeseam.analysis.relations.similarity import EXACT_TREE_SOURCES
from codeseam.platform import Json, json_int
from codeseam.semantics import SemanticEnrichmentRun, SemanticMode, SemanticProviderStatus


def run_completeness(  # noqa: PLR0913
    facts: RepositoryFacts,
    *,
    diagnostics: Mapping[str, tuple[str, ...]],
    function_count: int,
    comparison_stats: Json,
    capabilities: Sequence[AdapterCapabilitySummary],
    semantic_enrichment: SemanticEnrichmentRun,
    clusters: Clusters,
) -> CompletenessSummary:
    """Counts come from the scan and the final clusters, so a warm run reports the same."""

    selected = set(facts.selected_paths)
    unsupported = Counter(
        record.language for record in facts.records if record.language in OTHER_SOURCE_LANGUAGES
    )
    present = {facts.languages_by_path[path] for path in selected}
    results = semantic_enrichment.results
    sources = Counter(
        pair.tree.tree_distance_source in EXACT_TREE_SOURCES
        for pair in {
            id(pair): pair
            for cluster in clusters.clusters
            if cluster.enrichment is not None
            for pair in cluster.enrichment.structural_relation_pairs
        }.values()
    )
    return completeness_summary(
        CompletenessInputs(
            source_files=len(selected),
            diagnostics={path: items for path, items in diagnostics.items() if path in selected},
            unsupported_source_files=dict(unsupported),
            function_count=function_count,
            trees_measured=sources[True],
            trees_estimated=sources[False],
            comparison_stats={key: json_int(value) for key, value in comparison_stats.items()},
            policy_constant_languages=frozenset(
                summary.language
                for summary in capabilities
                if summary.capabilities.policy_constants and summary.language in present
            ),
            semantic_requested=semantic_enrichment.mode is not SemanticMode.OFF
            and bool(semantic_enrichment.requests),
            semantic_answered=sum(
                result.status is SemanticProviderStatus.READY for result in results
            ),
            semantic_caveats=tuple(dict.fromkeys(semantic_enrichment.caveats)),
        )
    )


__all__ = ["run_completeness"]
