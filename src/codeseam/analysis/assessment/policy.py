from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal, final

type ConfigSection = Mapping[str, object]
type RecommendationCapLabel = Literal[
    "allow_recommended_edit",
    "max_review_candidate",
    "max_maintenance_note",
    "max_observation",
    "do_not_refactor",
]


@final
class RecommendationCap:
    """Grouped actionability cap labels."""

    ALLOW_RECOMMENDED_EDIT: Final[RecommendationCapLabel] = "allow_recommended_edit"
    MAX_REVIEW_CANDIDATE: Final[RecommendationCapLabel] = "max_review_candidate"
    MAX_MAINTENANCE_NOTE: Final[RecommendationCapLabel] = "max_maintenance_note"
    MAX_OBSERVATION: Final[RecommendationCapLabel] = "max_observation"
    DO_NOT_REFACTOR: Final[RecommendationCapLabel] = "do_not_refactor"


@dataclass(frozen=True, slots=True)
class DetectionPolicy:
    """Interpretable anchors for relation-reality scoring."""

    policy_constant_confidence: float = field(
        default=0.98,
        metadata={"doc": "Confidence for duplicated policy literals found by exact analysis."},
    )
    structural_duplicate_min_confidence: float = field(
        default=0.90,
        metadata={"doc": "Minimum confidence for exact or near-exact structural duplicates."},
    )
    structural_relatedness_multiplier: float = field(
        default=0.85,
        metadata={"doc": "Multiplier converting relation relatedness into detection confidence."},
    )
    structural_relation_fallback_confidence: float = field(
        default=0.30,
        metadata={"doc": "Fallback confidence for structural pairs that lack scored evidence."},
    )
    argument_normalization_base_confidence: float = field(
        default=0.58,
        metadata={"doc": "Confidence for unsupported argument-normalization wrapper evidence."},
    )
    argument_normalization_supported_confidence: float = field(
        default=0.72,
        metadata={"doc": "Confidence for argument normalization with shared-operation support."},
    )
    proxy_base_confidence: float = field(
        default=0.40,
        metadata={"doc": "Confidence for call/control proxy evidence before support boosts."},
    )
    signature_only_base_confidence: float = field(
        default=0.18,
        metadata={"doc": "Confidence for recurrence visible only through signature shape."},
    )
    supporting_signal_boost: float = field(
        default=0.05,
        metadata={"doc": "Small bounded confidence boost per corroborating signal."},
    )
    structural_quality_cap: float = field(
        default=0.85,
        metadata={"doc": "Maximum confidence for non-exact structural relation evidence."},
    )
    proxy_quality_cap: float = field(
        default=0.60,
        metadata={"doc": "Maximum confidence for proxy-only evidence."},
    )
    min_recurrence_members: int = field(
        default=2,
        metadata={"doc": "Minimum members before signature recurrence is considered evidence."},
    )
    structural_tree_support_threshold: float = field(
        default=0.75,
        metadata={"doc": "Tree similarity threshold that counts as structural support."},
    )
    structural_name_support_threshold: float = field(
        default=0.65,
        metadata={"doc": "Name similarity threshold that counts as structural support."},
    )
    high_extraction_multiplier: float = field(
        default=1.0,
        metadata={"doc": "Detection multiplier for high-confidence extraction."},
    )
    medium_extraction_multiplier: float = field(
        default=0.90,
        metadata={"doc": "Detection multiplier for medium-confidence extraction."},
    )
    low_extraction_multiplier: float = field(
        default=0.75,
        metadata={"doc": "Detection multiplier for low-confidence extraction."},
    )
    unknown_extraction_multiplier: float = field(
        default=0.85,
        metadata={"doc": "Detection multiplier for missing or unrecognized extraction confidence."},
    )


@dataclass(frozen=True, slots=True)
class FitPolicy:
    """Interpretable anchors for abstraction-fit scoring."""

    structural_duplicate_commonality: float = field(
        default=0.90,
        metadata={"doc": "Commonality score for exact or near-exact structural duplicates."},
    )
    body_hash_commonality: float = field(
        default=0.95,
        metadata={"doc": "Commonality score when function body hashes match exactly."},
    )
    policy_constant_commonality: float = field(
        default=0.85,
        metadata={"doc": "Commonality score for duplicated policy constants."},
    )
    structural_relation_commonality: float = field(
        default=0.65,
        metadata={"doc": "Commonality score for non-identical structural relation evidence."},
    )
    structural_relation_floor: float = field(
        default=0.35,
        metadata={"doc": "Minimum commonality for structural relations with primitive support."},
    )
    weak_region_multiplier: float = field(
        default=0.35,
        metadata={"doc": "Commonality multiplier when a relation has weak stable-region support."},
    )
    tree_similarity_weight: float = field(
        default=0.75,
        metadata={"doc": "Weight for using tree similarity as structural commonality evidence."},
    )
    relatedness_weight: float = field(
        default=0.80,
        metadata={"doc": "Weight for using relation relatedness as commonality evidence."},
    )
    signature_only_commonality: float = field(
        default=0.15,
        metadata={"doc": "Commonality score for recurrence visible only through signature shape."},
    )
    stable_region_medium_at: int = field(
        default=2,
        metadata={"doc": "Stable statement count where common-region support starts."},
    )
    stable_region_high_at: int = field(
        default=5,
        metadata={"doc": "Stable statement count where common-region support is high."},
    )
    high_hole_count_at: int = field(
        default=3,
        metadata={"doc": "Hole count considered high abstraction complexity."},
    )
    high_hole_size_at: int = field(
        default=8,
        metadata={"doc": "Hole size considered high abstraction complexity."},
    )
    unknown_hole_simplicity: float = field(
        default=0.55,
        metadata={"doc": "Simplicity score when relation holes were not measured."},
    )
    high_relation_risk_at: float = field(
        default=0.35,
        metadata={"doc": "Relation-risk score that caps abstraction fit."},
    )
    high_abstraction_cost_at: float = field(
        default=0.65,
        metadata={"doc": "Abstraction-cost score that caps abstraction fit."},
    )
    recurrence_starts_at_members: int = field(
        default=2,
        metadata={"doc": "Minimum members before signature recurrence contributes to fit."},
    )
    weak_common_region_cap: float = field(
        default=0.35,
        metadata={"doc": "Maximum fit when related code has only a weak common region."},
    )
    high_cost_cap: float = field(
        default=0.40,
        metadata={"doc": "Maximum fit when abstraction cost is high."},
    )
    high_risk_cap: float = field(
        default=0.45,
        metadata={"doc": "Maximum fit when semantic relation risk is high."},
    )
    semantic_shared_implementation_boost: float = field(
        default=0.05,
        metadata={
            "doc": (
                "Small commonality boost when provider facts corroborate shared "
                "implementation targets and structural common-region evidence already exists."
            )
        },
    )
    parameterized_skeleton_simplicity: float = field(
        default=0.85,
        metadata={
            "doc": (
                "Simplicity score for near-identical same-skeleton helper variants that have "
                "already passed editable relation-evidence gates."
            )
        },
    )


@dataclass(frozen=True, slots=True)
class RelationEvidencePolicy:
    """Thresholds for interpreting scored relation evidence during assessment."""

    parameterized_skeleton_min_refactorability: float = field(
        default=0.75,
        metadata={
            "doc": (
                "Minimum refactorability for treating same-skeleton literal/callee variants as "
                "editable parameterized helper clones."
            )
        },
    )
    parameterized_skeleton_max_abstraction_cost: float = field(
        default=0.25,
        metadata={
            "doc": (
                "Maximum abstraction cost for same-skeleton variants before they remain "
                "maintenance-note/review evidence instead of edit evidence."
            )
        },
    )
    parameterized_skeleton_max_risk: float = field(
        default=0.30,
        metadata={"doc": "Maximum semantic risk for editable same-skeleton variants."},
    )
    parameterized_skeleton_min_tree_similarity: float = field(
        default=0.95,
        metadata={
            "doc": (
                "Minimum body-tree similarity for editable same-skeleton variants; this keeps "
                "the escape hatch limited to near-identical helper structure."
            )
        },
    )


@dataclass(frozen=True, slots=True)
class PayoffPolicy:
    """Interpretable anchors for maintenance-payoff scoring."""

    recurrence_starts_at_members: int = field(
        default=2,
        metadata={"doc": "Minimum members before repeated maintenance surface counts."},
    )
    recurrence_high_at_members: int = field(
        default=6,
        metadata={"doc": "Member count where recurrence contribution reaches its high anchor."},
    )
    material_line_span: int = field(
        default=12,
        metadata={"doc": "Line span where duplicated or related code starts to feel material."},
    )
    high_line_span: int = field(
        default=120,
        metadata={"doc": "Line span where volume contribution reaches its high anchor."},
    )
    local_duplicate_material_line_span: int = field(
        default=6,
        metadata={
            "doc": (
                "Total duplicated local block lines where intra-function duplicate payoff starts."
            )
        },
    )
    local_duplicate_high_line_span: int = field(
        default=18,
        metadata={
            "doc": "Total duplicated local block lines where local duplicate payoff is high."
        },
    )
    spread_starts_at_files: int = field(
        default=2,
        metadata={"doc": "Minimum distinct files before spread contributes to payoff."},
    )
    spread_high_at_files: int = field(
        default=5,
        metadata={"doc": "Distinct file count where spread contribution reaches its high anchor."},
    )
    structural_relation_quality: float = field(
        default=0.65,
        metadata={"doc": "Quality multiplier for non-identical structural relation evidence."},
    )
    signature_only_quality: float = field(
        default=0.15,
        metadata={"doc": "Quality multiplier for weak signature-only recurrence."},
    )
    test_fixture_exposure: float = field(
        default=0.45,
        metadata={"doc": "Exposure multiplier for test-only or fixture-only findings."},
    )
    unknown_role_exposure: float = field(
        default=0.70,
        metadata={"doc": "Exposure multiplier when member role cannot be classified."},
    )
    generated_vendor_cap: float = field(
        default=0.10,
        metadata={"doc": "Maximum payoff for generated, vendored, or build-output code."},
    )


@dataclass(frozen=True, slots=True)
class SemanticRoleCapPolicy:
    """Guardrails that cap actionability for protocol and API-surface code.

    These caps run after relation detection and scoring. They preserve the
    evidence that code is related, but prevent structurally similar protocol,
    framework, test, example, or generated surfaces from becoming edit
    recommendations by default.
    """

    tiny_body_line_count: int = field(
        default=5,
        metadata={"doc": "Maximum body size considered tiny protocol/API surface code."},
    )
    substantial_body_line_count: int = field(
        default=8,
        metadata={"doc": "Body size where protocol caps may relax by one tier."},
    )
    substantial_stable_statement_count: int = field(
        default=5,
        metadata={"doc": "Stable statement count that can relax a protocol cap."},
    )
    dominant_member_ratio: float = field(
        default=0.8,
        metadata={"doc": "Member ratio required before one semantic surface caps a target."},
    )
    material_duplicate_pair_ratio: float = field(
        default=0.67,
        metadata={
            "doc": (
                "Exact duplicate-pair ratio required before guarded protocol/API/example "
                "pairs cap a mixed target. Test duplicates are capped to review by default "
                "because their refactor economics differ from production code."
            )
        },
    )


@dataclass(frozen=True, slots=True)
class SemanticEvidencePolicy:
    """Generic scoring anchors for optional compiler/language-service facts.

    These values are deliberately language-neutral. Language adapters and
    semantic workers normalize provider-specific information upstream; the
    assessment layer only sees whether spans resolved, whether they are
    declaration-only surfaces, and whether related members share or diverge on
    resolved implementation targets.
    """

    declaration_surface_risk_unit: float = field(
        default=0.18,
        metadata={"doc": "Risk contribution for declaration-only semantic surfaces."},
    )
    unresolved_semantics_risk_unit: float = field(
        default=0.08,
        metadata={"doc": "Risk contribution when selected semantic spans did not resolve."},
    )
    ambiguous_ownership_risk_unit: float = field(
        default=0.12,
        metadata={"doc": "Risk contribution for ambiguous project/file ownership."},
    )
    divergent_call_target_risk_floor: float = field(
        default=0.45,
        metadata={
            "doc": ("Minimum semantic risk when same-looking calls resolve to different targets.")
        },
    )


@dataclass(frozen=True, slots=True)
class AssessmentPolicy:
    recommended_edit_threshold: float
    review_candidate_threshold: float
    high_band_threshold: float
    medium_band_threshold: float
    detection_relation_threshold: float
    fit_high_threshold: float
    fit_medium_threshold: float
    risk_cautious_threshold: float
    risk_block_threshold: float
    cost_block_threshold: float
    precision: int
    detection: DetectionPolicy = field(default_factory=DetectionPolicy)
    fit: FitPolicy = field(default_factory=FitPolicy)
    payoff: PayoffPolicy = field(default_factory=PayoffPolicy)
    semantic_caps: SemanticRoleCapPolicy = field(default_factory=SemanticRoleCapPolicy)
    semantic_evidence: SemanticEvidencePolicy = field(default_factory=SemanticEvidencePolicy)
    relation_evidence: RelationEvidencePolicy = field(default_factory=RelationEvidencePolicy)

    @classmethod
    def from_config(cls, config: ConfigSection) -> AssessmentPolicy:
        del config
        values = dict(DEFAULT_ASSESSMENT_VALUES)
        return cls(
            recommended_edit_threshold=_float(values, "recommended_edit_threshold"),
            review_candidate_threshold=_float(values, "review_candidate_threshold"),
            high_band_threshold=_float(values, "high_band_threshold"),
            medium_band_threshold=_float(values, "medium_band_threshold"),
            detection_relation_threshold=_float(values, "detection_relation_threshold"),
            fit_high_threshold=_float(values, "fit_high_threshold"),
            fit_medium_threshold=_float(values, "fit_medium_threshold"),
            risk_cautious_threshold=_float(values, "risk_cautious_threshold"),
            risk_block_threshold=_float(values, "risk_block_threshold"),
            cost_block_threshold=_float(values, "cost_block_threshold"),
            precision=int(_float(values, "precision")),
        )


DEFAULT_ASSESSMENT_VALUES: dict[str, object] = {
    "recommended_edit_threshold": 0.42,
    "review_candidate_threshold": 0.12,
    "high_band_threshold": 0.75,
    "medium_band_threshold": 0.45,
    "detection_relation_threshold": 0.35,
    "fit_high_threshold": 0.75,
    "fit_medium_threshold": 0.45,
    "risk_cautious_threshold": 0.30,
    "risk_block_threshold": 0.65,
    "cost_block_threshold": 0.65,
    "precision": 4,
}


def _float(config: Mapping[str, object], key: str) -> float:
    value = config[key]
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f"Expected numeric assessment value for {key!r}.")


__all__ = [
    "AssessmentPolicy",
    "ConfigSection",
    "DEFAULT_ASSESSMENT_VALUES",
    "DetectionPolicy",
    "FitPolicy",
    "PayoffPolicy",
    "RelationEvidencePolicy",
    "SemanticEvidencePolicy",
    "SemanticRoleCapPolicy",
]
