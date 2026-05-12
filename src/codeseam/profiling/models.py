from __future__ import annotations

import cProfile
from dataclasses import dataclass
from typing import Any

from codeseam.pipeline.signatures import SignatureArtifacts


@dataclass(frozen=True, slots=True)
class ProfileSource:
    selected_file_count: int
    function_count: int
    signature_artifacts: SignatureArtifacts


@dataclass(frozen=True, slots=True)
class ProfileCallCounts:
    operation_features_count: int = 0
    call_facts_count: int = 0


@dataclass(frozen=True, slots=True)
class ClusterProfileRow:
    cluster_id: str
    shape: str
    members: int
    candidates: int
    relations: int
    enrichment_ms: int
    candidate_ms: int
    relation_ms: int
    cache_hits: int
    cache_misses: int
    scope: str
    top_directories: tuple[str, ...]
    top_roles: tuple[str, ...]
    survival_rate: float


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    selected_file_count: int
    function_count: int
    signature_count: int
    cluster_count: int
    candidate_pair_count: int
    relation_pair_count: int
    operation_features_count: int
    call_facts_count: int
    top_clusters_by_enrichment_ms: tuple[ClusterProfileRow, ...]
    top_clusters_by_candidate_pairs: tuple[ClusterProfileRow, ...]
    top_clusters_by_relation_pairs: tuple[ClusterProfileRow, ...]
    top_clusters_by_cache_misses: tuple[ClusterProfileRow, ...]
    top_clusters_by_survival_rate: tuple[ClusterProfileRow, ...]

    def with_call_counts(self, counts: ProfileCallCounts) -> ProfileSummary:
        return ProfileSummary(
            selected_file_count=self.selected_file_count,
            function_count=self.function_count,
            signature_count=self.signature_count,
            cluster_count=self.cluster_count,
            candidate_pair_count=self.candidate_pair_count,
            relation_pair_count=self.relation_pair_count,
            operation_features_count=counts.operation_features_count,
            call_facts_count=counts.call_facts_count,
            top_clusters_by_enrichment_ms=self.top_clusters_by_enrichment_ms,
            top_clusters_by_candidate_pairs=self.top_clusters_by_candidate_pairs,
            top_clusters_by_relation_pairs=self.top_clusters_by_relation_pairs,
            top_clusters_by_cache_misses=self.top_clusters_by_cache_misses,
            top_clusters_by_survival_rate=self.top_clusters_by_survival_rate,
        )


@dataclass(frozen=True, slots=True)
class ProfileOutput:
    profiler: cProfile.Profile
    summary: ProfileSummary
    elapsed_seconds: float
    cache_mode: str
    cache_stats: dict[str, Any]
    sort: str
    limit: int
