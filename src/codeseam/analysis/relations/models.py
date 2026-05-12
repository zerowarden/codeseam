from __future__ import annotations

from dataclasses import dataclass, field

from codeseam.analysis.relations.feature_model import MemberFeatureCache, MemberFeatures
from codeseam.analysis.relations.kinds import (
    CALLSITE_EVIDENCE_KINDS,
    AbstractionKind,
    ActionKind,
    ActionStatus,
    CloneClass,
    DeltaKind,
    EvidenceKind,
    RelationKind,
    RiskKind,
    ScoreBand,
)
from codeseam.analysis.relations.member_model import (
    MemberInput,
    MemberRef,
    RelationMember,
    RelationMemberContext,
    member_digest_from_parts,
    member_ref,
)
from codeseam.analysis.relations.unification import SequenceSkeleton


@dataclass(frozen=True)
class SimilarityScores:
    name: float
    tree: float
    parameter: float
    call: float
    sequence: float
    graph: float

    def with_tree(self, value: float) -> SimilarityScores:
        return SimilarityScores(
            name=self.name,
            tree=value,
            parameter=self.parameter,
            call=self.call,
            sequence=self.sequence,
            graph=self.graph,
        )


@dataclass(frozen=True)
class SequenceComparison:
    lcs_length: int
    common_prefix_length: int
    common_suffix_length: int
    inserted_block_count: int
    inserted_block_position: str
    shared_argument_flow_in_tail: bool
    sequence_similarity: float
    left_statement_count: int
    right_statement_count: int
    max_statement_count: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_statement_count",
            max(self.left_statement_count, self.right_statement_count, 1),
        )


@dataclass(frozen=True)
class TreeComparison:
    tree_similarity: float
    tree_distance: float
    tree_edit_distance: int | None
    tree_node_count: int
    tree_distance_source: str


@dataclass(frozen=True)
class TreeEditDecision:
    compare_edit_distance: bool
    reject: bool
    proxy_tree_similarity: float
    tree_distance_source: str


@dataclass(frozen=True, slots=True)
class RelationScores:
    name: float
    parameter_use: float
    call_multiset: float
    graph: float
    relatedness: float
    refactorability: float
    abstraction_cost: float
    confidence: float
    risk: float


@dataclass(frozen=True, slots=True)
class RefactorabilityComponents:
    common_region_size: float = 0.0
    contiguous_common_region: float = 0.0
    low_hole_count: float = 0.0
    low_hole_complexity: float = 0.0
    same_return_shape: float = 0.0
    same_error_shape: float = 0.0
    same_source_role: float = 0.0
    local_module_scope: float = 0.0
    abstraction_cost_penalty: float = 0.0

    def total(self) -> float:
        return sum(
            (
                self.common_region_size,
                self.contiguous_common_region,
                self.low_hole_count,
                self.low_hole_complexity,
                self.same_return_shape,
                self.same_error_shape,
                self.same_source_role,
                self.local_module_scope,
                self.abstraction_cost_penalty,
            )
        )


@dataclass(frozen=True, slots=True)
class AbstractionCostComponents:
    parameter_count_estimate: float = 0.0
    hole_count: float = 0.0
    hole_complexity: float = 0.0
    branch_delta_count: float = 0.0
    local_temp_delta_count: float = 0.0
    callback_or_strategy_need: float = 0.0
    cross_module_dependency_cost: float = 0.0
    public_api_cost: float = 0.0

    def total(self) -> float:
        return sum(
            (
                self.parameter_count_estimate,
                self.hole_count,
                self.hole_complexity,
                self.branch_delta_count,
                self.local_temp_delta_count,
                self.callback_or_strategy_need,
                self.cross_module_dependency_cost,
                self.public_api_cost,
            )
        )


@dataclass(frozen=True)
class ArgumentNormalization:
    wrapper: str = ""
    primitive: str = ""
    wrapper_parameter_type: str = ""
    primitive_parameter_type: str = ""
    transform_tokens: tuple[str, ...] = ()
    shared_operation_tokens: tuple[str, ...] = ()
    interpretation: str = ""

    @property
    def is_detected(self) -> bool:
        return _argument_normalization_detected(self)


@dataclass(frozen=True, slots=True)
class RelationFlags:
    body_hash_match: bool
    same_signature_shape: bool
    same_tree: bool
    literal_shapes_differ: bool
    call_multiset_differs: bool
    same_call_multiset: bool
    control_vector_differs: bool
    parameter_flow_match: bool
    same_return_shape: bool
    same_error_shape: bool
    shared_argument_flow_through_tail: bool


@dataclass(frozen=True)
class RelationBasis:
    flags: RelationFlags
    argument_normalization: ArgumentNormalization
    shared_prefix_length: int
    shared_suffix_length: int
    lcs_length: int

    @property
    def argument_normalization_wrapper(self) -> bool:
        return _argument_normalization_detected(self.argument_normalization)


@dataclass(frozen=True)
class RelationBasisInput:
    sequence: SequenceComparison
    tree: TreeComparison
    parameter_similarity: float
    normalization: ArgumentNormalization


@dataclass(frozen=True)
class PairActionInput:
    left: MemberRef
    right: MemberRef
    relation_kind: RelationKind
    sequence: SequenceComparison
    normalization: ArgumentNormalization
    refactorability: float
    abstraction_cost: float
    confidence: float
    deltas: tuple[DeltaKind, ...]


@dataclass(frozen=True)
class RefactorAction:
    kind: ActionKind
    status: ActionStatus
    confidence: float
    applies_to: tuple[MemberRef, ...]
    preconditions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    normalization: ArgumentNormalization | None = None
    extracted_region_common_prefix_length: int = 0
    rejection_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefactorActionSummary:
    primary_action: ActionKind | None = None
    secondary_action: ActionKind | None = None
    not_recommended: tuple[ActionKind, ...] = ()
    primary_scope: str = ""
    secondary_scope: str = ""

    @property
    def has_actions(self) -> bool:
        return bool(self.primary_action or self.secondary_action or self.not_recommended)


def _argument_normalization_detected(normalization: ArgumentNormalization) -> bool:
    return bool(normalization.wrapper and normalization.primitive)


@dataclass(frozen=True)
class CloneClassification:
    clone_type: CloneClass
    syntactic_strength: str
    default_action: ActionKind
    basis: tuple[str, ...]


@dataclass(frozen=True)
class CloneClassificationInput:
    relation_kind: RelationKind
    scores: RelationScores
    flags: RelationFlags
    tree_similarity: float
    tree_distance_source: str
    parameter_similarity: float
    call_similarity: float
    sequence: SequenceComparison
    anti_unification: SequenceSkeleton
    deltas: tuple[DeltaKind, ...]
    refactorability: float
    abstraction_cost: float
    argument_normalization: ArgumentNormalization


@dataclass(frozen=True)
class RefactorShapeInput:
    anti_unification: SequenceSkeleton
    relation_kind: RelationKind
    clone_type: CloneClass
    default_action: ActionKind
    abstraction_cost: float
    delta_kinds: tuple[DeltaKind, ...]


@dataclass(frozen=True)
class HoleSize:
    min: int
    max: int


@dataclass(frozen=True)
class RefactorHole:
    id: str
    role: str
    type: str
    roles: tuple[str, ...]
    size: HoleSize
    variant_count: int
    member_bindings: dict[str, tuple[str, ...]]
    parameterization: str


@dataclass(frozen=True)
class RenderableSkeleton:
    language: str
    lines: tuple[str, ...]
    truncated: bool
    omitted_line_count: int
    validity: str
    validity_note: str
    suppressed: bool
    suppression_reason: str


@dataclass(frozen=True)
class AbstractionEstimate:
    hole_count: int
    statement_hole_count: int
    estimated_parameters: int | str
    estimated_callbacks: int
    estimated_parameter_range: str
    parameterization_confidence: str
    variation_points: tuple[str, ...] | str
    estimate_basis: str
    abstraction_cost: str


@dataclass(frozen=True)
class RefactorShape:
    shape_kind: str
    abstraction_domain: str
    skeleton_validity: str
    renderable_skeleton: RenderableSkeleton
    holes: tuple[RefactorHole, ...]
    abstraction_estimate: AbstractionEstimate
    recommendation: ActionKind
    caveats: tuple[str, ...]
    schema_version: str = "codeseam.refactor_shape.v1"


@dataclass(frozen=True, slots=True)
class AntiUnificationSummary:
    stable_statement_count: int = 0
    stable_node_ratio: float = 0.0
    common_prefix_length: int = 0
    common_suffix_length: int = 0
    common_prefix_ratio: float = 0.0
    hole_count: int = 0
    max_hole_size: int = 0
    hole_size_variance: str = ""
    shared_param_flow_through_holes: bool = False


def sequence_skeleton_summary(skeleton: SequenceSkeleton) -> AntiUnificationSummary:
    return AntiUnificationSummary(
        stable_statement_count=skeleton.stable_statement_count,
        stable_node_ratio=skeleton.stable_node_ratio,
        common_prefix_length=skeleton.common_prefix_length,
        common_suffix_length=skeleton.common_suffix_length,
        common_prefix_ratio=skeleton.common_prefix_ratio,
        hole_count=skeleton.hole_count,
        max_hole_size=skeleton.max_hole_size,
        hole_size_variance=skeleton.hole_size_variance,
        shared_param_flow_through_holes=skeleton.shared_param_flow_through_holes,
    )


@dataclass(frozen=True, slots=True)
class CachedRelationSummary:
    cache_key: str
    scores: RelationScores
    tree: TreeComparison
    sequence: SequenceComparison
    flags: RelationFlags
    normalization: ArgumentNormalization
    anti_unification: AntiUnificationSummary
    relation_kind: RelationKind
    relation_kinds: tuple[RelationKind, ...]
    clone_family: CloneClass
    clone_type: CloneClass
    recommended_action: ActionKind
    refactorability_kind: ScoreBand
    delta_kinds: tuple[DeltaKind, ...]
    same_role: bool
    role: str
    max_body_line_count: int
    min_body_line_count: int = 0
    refactor_action_candidates: tuple[RefactorAction, ...] = ()


@dataclass(frozen=True)
class RelationPair:
    abstraction_cost_components: AbstractionCostComponents
    anti_unification: SequenceSkeleton
    anti_unification_summary: AntiUnificationSummary
    clone_classification: CloneClassification
    clone_family: CloneClass
    clone_type: CloneClass
    delta_kinds: tuple[DeltaKind, ...]
    flags: RelationFlags
    left: MemberRef
    max_body_line_count: int
    recommended_action: ActionKind
    refactorability_components: RefactorabilityComponents
    refactorability_kind: ScoreBand
    refactor_action_candidates: tuple[RefactorAction, ...]
    relation_basis: RelationBasis
    relation_kind: RelationKind
    relation_kinds: tuple[RelationKind, ...]
    right: MemberRef
    role: str
    same_role: bool
    scores: RelationScores
    sequence: SequenceComparison
    tree: TreeComparison
    min_body_line_count: int = 0
    refactor_shape: RefactorShape | None = None
    schema_version: str = "codeseam.structural_relation_pair.v1"
    score_model: str = "heuristic_v1"
    score_interpretation: str = "ranking_signal_not_probability"


__all__ = [
    "AbstractionCostComponents",
    "AbstractionEstimate",
    "AbstractionKind",
    "AntiUnificationSummary",
    "ArgumentNormalization",
    "ActionKind",
    "ActionStatus",
    "CALLSITE_EVIDENCE_KINDS",
    "CachedRelationSummary",
    "CloneClass",
    "CloneClassification",
    "CloneClassificationInput",
    "DeltaKind",
    "EvidenceKind",
    "MemberRef",
    "MemberFeatureCache",
    "MemberFeatures",
    "MemberInput",
    "HoleSize",
    "PairActionInput",
    "RefactorHole",
    "RefactorAction",
    "RefactorActionSummary",
    "RefactorShape",
    "RefactorShapeInput",
    "RenderableSkeleton",
    "RelationPair",
    "RelationBasis",
    "RelationBasisInput",
    "RelationFlags",
    "RelationMember",
    "RelationMemberContext",
    "RelationKind",
    "RelationScores",
    "RefactorabilityComponents",
    "RiskKind",
    "ScoreBand",
    "SequenceComparison",
    "SimilarityScores",
    "TreeComparison",
    "TreeEditDecision",
    "member_ref",
    "member_digest_from_parts",
    "sequence_skeleton_summary",
]
