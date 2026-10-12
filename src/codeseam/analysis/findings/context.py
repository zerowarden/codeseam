"""The aggregated cluster evidence that signature drafts are built from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeseam.analysis.clusters import (
    CandidateGenerationSummary,
    Cluster,
    StructuralSubcluster,
)
from codeseam.analysis.findings.models import (
    FindingLocation,
    SemanticEvidenceMetrics,
)
from codeseam.analysis.findings.semantic_evidence import SemanticEvidenceIndex
from codeseam.analysis.relations.models import (
    AbstractionRisk,
    RefactorAction,
    RefactorActionSummary,
    RelationPair,
)
from codeseam.analysis.signatures import (
    CallsitePattern,
    NormalizationLevel,
    SignatureCore,
)


@dataclass(frozen=True, slots=True)
class SignatureDraftContext:
    """Aggregated post-cache evidence needed to build finding drafts.

    This context is intentionally internal to draft construction.
    it only gives the reporting and assessment layer one coherent view
    of already-computed cluster evidence.
    """

    cluster: Cluster
    members: tuple[SignatureCore, ...]
    files: list[str]
    evidence_kinds: list[str]
    callsite_patterns: list[CallsitePattern]
    abstraction_risks: list[AbstractionRisk]
    structural_pairs: list[RelationPair]
    relation_pairs: list[RelationPair]
    promoted_components: list[list[RelationPair]]
    subclusters: list[StructuralSubcluster]
    actions: list[RefactorAction]
    action_summary: RefactorActionSummary | None
    candidate_generation: CandidateGenerationSummary | None
    structural_metrics: dict[str, Any]
    normalization_level: NormalizationLevel
    locations: list[FindingLocation]
    sync_async_cluster: bool
    semantic_role_counts: dict[str, int]
    semantic_role_reasons: tuple[str, ...]
    semantic_role_member_metrics: dict[str, int]
    semantic_evidence: SemanticEvidenceMetrics
    semantic_evidence_index: SemanticEvidenceIndex


__all__ = ["SignatureDraftContext"]
