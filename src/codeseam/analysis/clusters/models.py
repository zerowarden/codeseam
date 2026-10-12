from __future__ import annotations

from collections.abc import Sized
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

from codeseam.analysis.relations.enrichment_models import ClusterEnrichment
from codeseam.analysis.relations.models import (
    RefactorAction,
    RefactorActionSummary,
)
from codeseam.analysis.signatures import (
    AdapterId,
    ExtractionConfidence,
    LanguageFamily,
    NormalizationLevel,
    PolicyConstant,
    SignatureCore,
)


@dataclass(frozen=True)
class ClusterMember:
    signature: SignatureCore
    language: str = ""
    language_family: LanguageFamily = LanguageFamily.UNKNOWN
    adapter: AdapterId = AdapterId.UNKNOWN


class _HasMembers(Protocol):
    members: Sized


@dataclass(frozen=True)
class _MemberCounted:
    member_count: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "member_count",
            _member_count(cast(_HasMembers, self).members),
        )


@dataclass(frozen=True)
class Cluster(_MemberCounted):
    cluster_id: str
    language: str
    shape_hash: str
    canonical_shape: str
    members: tuple[ClusterMember, ...]
    overlaps: dict[str, tuple[str, ...]]
    review_relevance: str
    priority_hint: str
    non_claims: tuple[str, ...]
    cluster_scope: str
    languages: tuple[str, ...]
    language_count: int
    language_families: tuple[LanguageFamily, ...]
    language_family_count: int
    adapters: tuple[AdapterId, ...]
    adapter_count: int
    min_extraction_confidence: ExtractionConfidence
    normalization_level: NormalizationLevel
    enrichment: ClusterEnrichment | None = None
    schema_version: str = "codeseam.signature_cluster.v1"


class PolicyConstantMatch(StrEnum):
    IDENTICAL = "identical"  # same name, same literal
    DRIFTED = "drifted"  # same name, overlapping but different literals
    SCATTERED = "scattered"  # same literal under different names


@dataclass(frozen=True)
class PolicyConstantCluster(_MemberCounted):
    match: PolicyConstantMatch
    cluster_id: str
    language: str
    shape_hash: str
    canonical_shape: str
    members: tuple[PolicyConstant, ...]
    review_relevance: str
    priority_hint: str
    confidence: float
    evidence_kinds: tuple[str, ...]
    abstraction_kind: str
    refactor_action_candidates: tuple[RefactorAction, ...]
    refactor_action_summary: RefactorActionSummary
    non_claims: tuple[str, ...]
    schema_version: str = "codeseam.policy_constant_cluster.v1"


def _member_count(members: Sized) -> int:
    return len(members)


@dataclass(frozen=True)
class Clusters:
    clusters: tuple[Cluster, ...]
    policy_constant_clusters: tuple[PolicyConstantCluster, ...]
    schema_version: str = "codeseam.signature_clusters.v1"
    same_language_cluster_count: int = field(init=False)
    adapter_wrapper_cluster_count: int = field(init=False)
    analogous_cluster_count: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "same_language_cluster_count",
            sum(1 for cluster in self.clusters if cluster.cluster_scope == "same_language"),
        )
        object.__setattr__(
            self,
            "adapter_wrapper_cluster_count",
            sum(
                1
                for cluster in self.clusters
                if cluster.enrichment
                and "argument_normalization_wrapper" in cluster.enrichment.evidence_kinds
            ),
        )
        object.__setattr__(
            self,
            "analogous_cluster_count",
            sum(1 for cluster in self.clusters if cluster.cluster_scope != "same_language"),
        )


__all__ = [
    "Cluster",
    "ClusterMember",
    "Clusters",
    "PolicyConstantCluster",
    "PolicyConstantMatch",
]
