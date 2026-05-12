from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from codeseam.analysis.assessment import ContextClassification
from codeseam.analysis.assessment.cluster import (
    Cluster,
    PolicyConstantCluster,
    StructuralSubcluster,
)
from codeseam.analysis.assessment.definitions import (
    EvidenceStrength,
    ExtractionConfidence,
    FindingActionStatus,
    FindingReviewVisibility,
    FindingTargetType,
    ReviewTier,
)
from codeseam.analysis.relations.models import (
    ActionKind,
    RefactorAction,
    RefactorActionSummary,
    RelationPair,
)
from codeseam.analysis.signatures import NormalizationLevel


@dataclass(frozen=True)
class FindingInputs:
    signature_clusters: tuple[Cluster, ...]
    policy_constant_clusters: tuple[PolicyConstantCluster, ...]


@dataclass(frozen=True)
class FindingLocation:
    file: str
    start_line: int
    end_line: int
    source: str
    kind: str
    symbol: str
    message: str = ""


@dataclass(frozen=True)
class EvidenceItem:
    kind: str
    id: str = ""


@dataclass(frozen=True, slots=True)
class RoleEvidenceCounts:
    """Role evidence counts used by semantic action guardrails."""

    members: int = 0
    duplicate_pairs: int = 0
    relation_pairs: int = 0


@dataclass(frozen=True, slots=True)
class SemanticGuardrailMetrics:
    """Grouped role evidence derived from the flat finding metrics payload.

    `FindingMetrics` remains flat because it is serialized into reports and
    cache/debug artifacts. Assessment code should use this grouped view when it
    needs to reason about role dominance across members and relation pairs.
    """

    api_surface: RoleEvidenceCounts = RoleEvidenceCounts()
    constructor: RoleEvidenceCounts = RoleEvidenceCounts()
    declaration: RoleEvidenceCounts = RoleEvidenceCounts()
    example: RoleEvidenceCounts = RoleEvidenceCounts()
    interface_only: RoleEvidenceCounts = RoleEvidenceCounts()
    protocol: RoleEvidenceCounts = RoleEvidenceCounts()
    test: RoleEvidenceCounts = RoleEvidenceCounts()


@dataclass(frozen=True, slots=True)
class SemanticEvidenceMetrics:
    """Compact provider facts attached after optional semantic enrichment.

    Language workers return typed enrichment records upstream; finding construction summarizes
    them here so detection/fit/risk can score the same language-neutral facts
    regardless of whether they came from TypeScript, Rust, Swift, or another
    provider. Output serializers are responsible for converting this dataclass
    into JSON.
    """

    unresolved_item_count: int = 0
    ambiguous_ownership_count: int = 0
    declaration_only_count: int = 0
    same_overload_group_pair_count: int = 0
    shared_call_target_pair_count: int = 0
    divergent_call_target_pair_count: int = 0

    @property
    def shared_implementation_pair_count(self) -> int:
        return self.same_overload_group_pair_count + self.shared_call_target_pair_count


@dataclass(frozen=True, slots=True)
class FindingMetrics:
    adapter_count: int = 1
    api_surface_duplicate_pair_count: int = 0
    api_surface_member_count: int = 0
    api_surface_relation_pair_count: int = 0
    body_hash_match_count: int = 0
    call_fingerprint_count: int = 0
    canonical_shape: str = ""
    clone_type_counts: dict[str, int] | None = None
    cluster_scope: str = "same_language"
    constructor_duplicate_pair_count: int = 0
    constructor_relation_pair_count: int = 0
    control_context_count: int = 0
    declaration_duplicate_pair_count: int = 0
    declaration_member_count: int = 0
    declaration_relation_pair_count: int = 0
    delta_kind_counts: dict[str, int] | None = None
    example_duplicate_pair_count: int = 0
    example_member_count: int = 0
    example_relation_pair_count: int = 0
    guardrail_relation_pair_count: int = 0
    interface_only_duplicate_pair_count: int = 0
    interface_only_member_count: int = 0
    interface_only_relation_pair_count: int = 0
    intra_function_duplicate_block_count: int = 0
    intra_function_duplicate_line_count: int = 0
    language_count: int = 1
    max_abstraction_cost_score: float = 0.0
    max_body_line_count: int = 0
    max_hole_count: int = 0
    max_hole_size: int = 0
    max_name_similarity: float = 0.0
    max_refactorability_score: float = 0.0
    max_relatedness_score: float = 0.0
    max_relation_confidence_score: float = 0.0
    max_relation_risk_score: float = 0.0
    max_stable_statement_count: int = 0
    max_tree_node_count: int = 0
    max_tree_similarity: float = 0.0
    member_count: int = 0
    min_body_line_count: int = 0
    min_extraction_confidence: ExtractionConfidence = ExtractionConfidence.HIGH
    min_stable_statement_count: int = 0
    normalization_level: NormalizationLevel = NormalizationLevel.SIGNATURE
    policy_constant_duplicate_count: int = 0
    protocol_duplicate_pair_count: int = 0
    protocol_member_count: int = 0
    protocol_relation_pair_count: int = 0
    promoted_exact_pair_count: int = 0
    promoted_exact_pair_member_count: int = 0
    relation_kind_counts: dict[str, int] | None = None
    same_directory_relation_count: int = 0
    same_role_relation_count: int = 0
    semantic_role_counts: dict[str, int] | None = None
    semantic_role_reasons: tuple[str, ...] = ()
    semantic_evidence: SemanticEvidenceMetrics = field(default_factory=SemanticEvidenceMetrics)
    structural_duplicate_pair_count: int = 0
    structural_relation_pair_count: int = 0
    test_duplicate_pair_count: int = 0
    test_member_count: int = 0
    test_relation_pair_count: int = 0

    @property
    def semantic_guardrails(self) -> SemanticGuardrailMetrics:
        return SemanticGuardrailMetrics(
            api_surface=RoleEvidenceCounts(
                members=self.api_surface_member_count,
                duplicate_pairs=self.api_surface_duplicate_pair_count,
                relation_pairs=self.api_surface_relation_pair_count,
            ),
            constructor=RoleEvidenceCounts(
                members=0,
                duplicate_pairs=self.constructor_duplicate_pair_count,
                relation_pairs=self.constructor_relation_pair_count,
            ),
            declaration=RoleEvidenceCounts(
                members=self.declaration_member_count,
                duplicate_pairs=self.declaration_duplicate_pair_count,
                relation_pairs=self.declaration_relation_pair_count,
            ),
            example=RoleEvidenceCounts(
                members=self.example_member_count,
                duplicate_pairs=self.example_duplicate_pair_count,
                relation_pairs=self.example_relation_pair_count,
            ),
            interface_only=RoleEvidenceCounts(
                members=self.interface_only_member_count,
                duplicate_pairs=self.interface_only_duplicate_pair_count,
                relation_pairs=self.interface_only_relation_pair_count,
            ),
            protocol=RoleEvidenceCounts(
                members=self.protocol_member_count,
                duplicate_pairs=self.protocol_duplicate_pair_count,
                relation_pairs=self.protocol_relation_pair_count,
            ),
            test=RoleEvidenceCounts(
                members=self.test_member_count,
                duplicate_pairs=self.test_duplicate_pair_count,
                relation_pairs=self.test_relation_pair_count,
            ),
        )


@dataclass(frozen=True)
class FindingDecision:
    review_tier: ReviewTier
    review_score: float
    action_status: FindingActionStatus
    primary_action: ActionKind
    evidence_strength: EvidenceStrength
    relatedness_score: float
    refactorability_score: float
    abstraction_cost_score: float
    risk_score: float
    confidence: float
    evidence_classes: tuple[str, ...]
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class FindingDraft:
    confidence: float
    direction: str
    evidence: list[EvidenceItem]
    files: list[str]
    locations: list[FindingLocation]
    metrics: FindingMetrics
    overlaps: dict[str, tuple[str, ...]]
    reasons: list[str]
    risk: str
    severity: str
    target_type: FindingTargetType
    title: str
    member_count: int = 1
    abstraction_kind: str | None = None
    abstraction_risks: Sequence[object] | None = None
    callsite_patterns: Sequence[object] | None = None
    candidate_generation: object | None = None
    context_classifications: list[ContextClassification] | None = None
    evidence_kinds: list[str] | None = None
    has_signature_overlap: bool = False
    line_span: int = 0
    non_claims: list[str] | None = None
    refactor_action_candidates: list[RefactorAction] | None = None
    refactor_action_summary: RefactorActionSummary | None = None
    structural_relation_pairs: list[RelationPair] | None = None
    structural_subclusters: list[StructuralSubcluster] | None = None


@dataclass(frozen=True)
class Finding:
    target_type: FindingTargetType
    title: str
    review_tier: ReviewTier
    review_score: float
    action_status: FindingActionStatus
    primary_action: ActionKind
    visibility: FindingReviewVisibility
    summary_eligible: bool
    evidence_strength: EvidenceStrength
    relatedness_score: float
    refactorability_score: float
    abstraction_cost_score: float
    risk_score: float
    evidence_classes: tuple[str, ...]
    decision: FindingDecision
    severity: str
    confidence: float
    detection_confidence: float
    recommendation_confidence: float
    score_model: str
    score_interpretation: str
    assessment: object
    evidence: tuple[EvidenceItem, ...]
    reasons: tuple[str, ...]
    non_claims: tuple[str, ...]
    suggested_refactor_direction: str
    risk: str
    files: tuple[str, ...]
    locations: tuple[FindingLocation, ...]
    metrics: FindingMetrics
    overlaps: dict[str, tuple[str, ...]]
    lifecycle: object
    abstraction_kind: str = ""
    abstraction_risks: tuple[object, ...] = ()
    evidence_kinds: tuple[str, ...] = ()
    callsite_patterns: tuple[object, ...] = ()
    structural_relation_pairs: tuple[RelationPair, ...] = ()
    structural_subclusters: tuple[StructuralSubcluster, ...] = ()
    candidate_generation: object | None = None
    refactor_action_candidates: tuple[RefactorAction, ...] = ()
    refactor_action_summary: RefactorActionSummary | None = None
    context_classifications: tuple[ContextClassification, ...] = ()
    finding_kind: str = ""
    context_tags: tuple[str, ...] = ()
    downgrade_reasons: tuple[str, ...] = ()
    refactor_value: str = ""
    refactor_safety: str = ""
    summary_reason: str = ""
    target_id: str = ""
    identity_hash: str = ""
    rank: int = 0
    rank_label: str = ""


__all__ = [
    "FindingInputs",
    "FindingDraft",
    "Finding",
    "FindingDecision",
    "FindingLocation",
    "FindingMetrics",
    "RoleEvidenceCounts",
    "SemanticGuardrailMetrics",
    "SemanticEvidenceMetrics",
    "EvidenceItem",
]
