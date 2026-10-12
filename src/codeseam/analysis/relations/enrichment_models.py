"""What relation analysis reports about one cluster: summary, pairs, subclusters, actions."""

from __future__ import annotations

from dataclasses import dataclass

from codeseam.analysis.relations.models import (
    AbstractionRisk,
    ActionKind,
    CloneClass,
    MemberRef,
    RefactorAction,
    RefactorActionSummary,
    RelationKind,
    RelationPair,
    ScoreBand,
)
from codeseam.analysis.signatures import CallsitePattern


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


__all__ = [
    "CandidateGenerationSummary",
    "ClusterEnrichment",
    "ClusterSummary",
    "LineRange",
    "StructuralSubcluster",
    "SubclusterScores",
]
