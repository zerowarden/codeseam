from __future__ import annotations

import cProfile
from collections import Counter
from collections.abc import Callable, Iterable

from codeseam.analysis import Cluster
from codeseam.pipeline.signatures import SignatureArtifacts
from codeseam.profiling.models import (
    ClusterProfileRow,
    ProfileCallCounts,
    ProfileSource,
    ProfileSummary,
)

PROFILE_TOP_LIMIT = 5


def collect_analysis_profile(
    *,
    selected_file_count: int,
    function_count: int,
    signature_artifacts: SignatureArtifacts,
) -> ProfileSummary:
    rows = tuple(_cluster_profile_row(cluster) for cluster in signature_artifacts.clusters.clusters)
    candidate_pair_count = sum(row.candidates for row in rows)
    relation_pair_count = sum(row.relations for row in rows)
    return ProfileSummary(
        selected_file_count=selected_file_count,
        function_count=function_count,
        signature_count=len(signature_artifacts.records),
        cluster_count=len(signature_artifacts.clusters.clusters),
        candidate_pair_count=candidate_pair_count,
        relation_pair_count=relation_pair_count,
        operation_features_count=0,
        call_facts_count=0,
        top_clusters_by_enrichment_ms=_top(rows, lambda row: row.enrichment_ms),
        top_clusters_by_candidate_pairs=_top(rows, lambda row: row.candidates),
        top_clusters_by_relation_pairs=_top(rows, lambda row: row.relations),
        top_clusters_by_cache_misses=_top(
            rows,
            lambda row: row.cache_misses,
            require_positive=True,
        ),
        top_clusters_by_survival_rate=_top(rows, lambda row: row.survival_rate),
    )


def collect_profile_summary(source: ProfileSource, profiler: cProfile.Profile) -> ProfileSummary:
    return collect_analysis_profile(
        selected_file_count=source.selected_file_count,
        function_count=source.function_count,
        signature_artifacts=source.signature_artifacts,
    ).with_call_counts(profile_call_counts(profiler))


def profile_call_counts(profiler: cProfile.Profile) -> ProfileCallCounts:
    operation_features_count = 0
    call_facts_count = 0
    for entry in profiler.getstats():
        code = entry.code
        name = getattr(code, "co_name", "")
        if name == "operation_features":
            operation_features_count += int(entry.callcount)
        elif name == "_call_facts":
            call_facts_count += int(entry.callcount)
    return ProfileCallCounts(
        operation_features_count=operation_features_count,
        call_facts_count=call_facts_count,
    )


def _cluster_profile_row(cluster: Cluster) -> ClusterProfileRow:
    enrichment = cluster.enrichment
    candidate = enrichment.candidate_generation if enrichment else None
    stats = candidate.comparison_stats if candidate else {}
    candidates = candidate.candidate_pair_count if candidate else 0
    relations = int(stats.get("relation_pair_count", 0))
    return ClusterProfileRow(
        cluster_id=cluster.cluster_id,
        shape=cluster.canonical_shape,
        members=len(cluster.members),
        candidates=candidates,
        relations=relations,
        enrichment_ms=int(stats.get("profile_enrichment_ms", 0)),
        candidate_ms=int(stats.get("profile_candidate_ms", 0)),
        relation_ms=int(stats.get("profile_relation_ms", 0)),
        cache_hits=int(stats.get("cache_hit_count", 0))
        + int(stats.get("group_cache_hit_count", 0)),
        cache_misses=int(stats.get("cache_miss_count", 0))
        + int(stats.get("group_cache_miss_count", 0)),
        scope=candidate.implemented_scope if candidate else cluster.cluster_scope,
        top_directories=_top_labels(
            _directories(member.signature.file for member in cluster.members)
        ),
        top_roles=_top_labels(member.signature.role for member in cluster.members),
        survival_rate=round(relations / candidates, 4) if candidates else 0.0,
    )


def _directories(files: Iterable[str]) -> Iterable[str]:
    for file in files:
        parts = file.split("/")
        yield parts[0] if len(parts) == 1 else "/".join(parts[:2])


def _top_labels(values: Iterable[str]) -> tuple[str, ...]:
    counts = Counter(value for value in values if value)
    return tuple(label for label, _ in counts.most_common(3))


def _top(
    rows: tuple[ClusterProfileRow, ...],
    key: Callable[[ClusterProfileRow], float | int],
    *,
    require_positive: bool = False,
) -> tuple[ClusterProfileRow, ...]:
    selected = tuple(row for row in rows if key(row) > 0) if require_positive else rows
    return tuple(
        sorted(
            selected,
            key=lambda row: (
                -float(key(row)),
                row.cluster_id,
            ),
        )[:PROFILE_TOP_LIMIT]
    )
