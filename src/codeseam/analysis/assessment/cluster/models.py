from __future__ import annotations

from collections.abc import Sized
from dataclasses import dataclass, field
from typing import Protocol, cast

from codeseam.analysis.assessment.definitions import ExtractionConfidence
from codeseam.analysis.assessment.models import AbstractionRisk, ContextClassification
from codeseam.analysis.relations.models import (
    ActionKind,
    CloneClass,
    MemberRef,
    RefactorAction,
    RefactorActionSummary,
    RelationKind,
    RelationPair,
    ScoreBand,
)
from codeseam.analysis.signatures import (
    AdapterId,
    CallsitePattern,
    LanguageFamily,
    NormalizationLevel,
    PolicyConstant,
    SignatureCore,
)


@dataclass(frozen=True)
class CandidateGenerationSummary:
    methods: tuple[str, ...]
    implemented_scope: str
    member_count: int
    eligible_member_count: int
    candidate_pair_count: int
    comparison_stats: dict[str, int]
    candidate_pair_limit: int
    bucket_member_limit: int
    max_statement_count: int
    max_tree_node_count: int
    shape_hash_count: int
    body_hash_count: int
    name_token_bucket_count: int
    call_fingerprint_token_count: int


@dataclass(frozen=True)
class LineRange:
    file: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ClusterSummary:
    member_count: int
    representative_files: tuple[str, ...]
    representative_symbols: tuple[str, ...]
    line_ranges: tuple[LineRange, ...]
    evidence_kinds: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class SubclusterScores:
    max_relatedness: float
    mean_relatedness: float
    max_refactorability: float
    mean_refactorability: float


@dataclass(frozen=True)
class StructuralSubcluster:
    subcluster_id: str
    relation_kind: RelationKind
    clone_family: CloneClass
    clone_type: CloneClass
    recommended_action: ActionKind
    refactorability_kind: ScoreBand
    pair_count: int
    members: tuple[MemberRef, ...]
    scores: SubclusterScores


@dataclass(frozen=True)
class ClusterMember:
    signature: SignatureCore
    language: str = ""
    language_family: LanguageFamily = LanguageFamily.UNKNOWN
    adapter: AdapterId = AdapterId.UNKNOWN


@dataclass(frozen=True)
class ClusterEnrichment:
    cluster_summary: ClusterSummary
    confidence: float
    evidence_kinds: tuple[str, ...]
    callable_factory_members: tuple[MemberRef, ...]
    callsite_patterns: tuple[CallsitePattern, ...]
    structural_relation_pairs: tuple[RelationPair, ...]
    structural_duplicate_pairs: tuple[RelationPair, ...]
    structural_subclusters: tuple[StructuralSubcluster, ...]
    candidate_generation: CandidateGenerationSummary
    refactor_action_candidates: tuple[RefactorAction, ...]
    refactor_action_summary: RefactorActionSummary
    abstraction_kind: str
    abstraction_risks: tuple[AbstractionRisk, ...]
    context_classifications: tuple[ContextClassification, ...] = ()


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


@dataclass(frozen=True)
class PolicyConstantCluster(_MemberCounted):
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
    "CandidateGenerationSummary",
    "Cluster",
    "ClusterEnrichment",
    "ClusterMember",
    "ClusterSummary",
    "Clusters",
    "LineRange",
    "PolicyConstantCluster",
    "StructuralSubcluster",
    "SubclusterScores",
]
