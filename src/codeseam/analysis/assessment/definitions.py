from __future__ import annotations

from enum import StrEnum


class AssessmentBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class AssessmentGate(StrEnum):
    ARGUMENT_NORMALIZATION_DETECTED = "argument_normalization_detected"
    BODY_HASH_OR_NEAR_IDENTICAL_TREE = "body_hash_or_near_identical_tree"
    BOUNDED_ABSTRACTION_COST = "bounded_abstraction_cost"
    CLEAN_CLONE_RELATION = "clean_clone_relation"
    CLEAR_BOUNDARY_OWNER = "clear_boundary_owner"
    EXISTING_HELPER_BOUNDARY = "existing_helper_boundary"
    EXPLICIT_SAFETY_STOP = "explicit_safety_stop"
    INTRA_FUNCTION_DUPLICATE_BLOCK = "intra_function_duplicate_block"
    INVENTORY_ONLY = "inventory_only"
    LOW_ABSTRACTION_COST = "low_abstraction_cost"
    LOW_BRANCH_DELTA = "low_branch_delta"
    LOW_HOLE_COMPLEXITY = "low_hole_complexity"
    LOW_HOLE_COUNT = "low_hole_count"
    LOW_PUBLIC_API_COST = "low_public_api_cost"
    LOW_SEMANTIC_RISK = "low_semantic_risk"
    MAINTENANCE_PAYOFF = "maintenance_payoff"
    RELATION_DETECTED = "relation_detected"
    REVIEWABLE_SEMANTIC_RISK = "reviewable_semantic_risk"
    SAME_DOWNSTREAM_OPERATION = "same_downstream_operation"
    SAME_ROLE_SEMANTICS = "same_role_semantics"
    SHARED_CONCERN_ONLY = "shared_concern_only"
    SHARED_LIFECYCLE_ONLY = "shared_lifecycle_only"
    SIMPLE_ARGUMENT_TRANSFORM = "simple_argument_transform"
    SMALL_COMMON_BODY = "small_common_body"
    STABLE_COMMON_REGION = "stable_common_region"
    SUBSTANTIAL_LOCAL_DUPLICATE_BLOCK = "substantial_local_duplicate_block"


class EvidenceQuality(StrEnum):
    EXACT = "exact"
    STRUCTURAL = "structural"
    PROXY = "proxy"
    SIGNATURE_ONLY = "signature_only"


class EvidenceStrength(StrEnum):
    NONE = ""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class ExtractionConfidence(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {
            ExtractionConfidence.UNKNOWN: 0,
            ExtractionConfidence.LOW: 1,
            ExtractionConfidence.MEDIUM: 2,
            ExtractionConfidence.HIGH: 3,
        }[self]


class FindingActionStatus(StrEnum):
    RECOMMENDED_EDIT = "recommended_edit"
    CAUTIOUS_CANDIDATE = "cautious_candidate"
    RECORD_SHARED_CONCERN = "record_shared_concern"
    OBSERVE = "observe"
    DO_NOT_REFACTOR = "do_not_refactor"


class FindingReviewVisibility(StrEnum):
    LISTED = "listed"
    GROUPED = "grouped"
    SIDECAR_ONLY = "sidecar_only"


class FindingTargetType(StrEnum):
    SIGNATURE_SHAPE = "file_module_concern"


class FindingVisibility(StrEnum):
    AGENT_SUMMARY = "agent_summary"
    SUMMARY_GROUPED = "summary_grouped"
    SIDECAR_ONLY = "sidecar_only"


class RecommendationStatus(StrEnum):
    RECOMMENDED = "recommended"
    CAUTIOUS = "cautious"
    NOT_RECOMMENDED = "not_recommended"


class ReviewTier(StrEnum):
    RECOMMENDED_EDIT = "recommended_edit"
    REVIEW_CANDIDATE = "review_candidate"
    MAINTENANCE_NOTE = "maintenance_note"
    OBSERVATION = "observation"


REVIEW_TIERS: tuple[ReviewTier, ...] = (
    ReviewTier.RECOMMENDED_EDIT,
    ReviewTier.REVIEW_CANDIDATE,
    ReviewTier.MAINTENANCE_NOTE,
    ReviewTier.OBSERVATION,
)

REVIEW_TIER_ORDER: dict[ReviewTier, int] = {
    ReviewTier.RECOMMENDED_EDIT: 0,
    ReviewTier.REVIEW_CANDIDATE: 1,
    ReviewTier.MAINTENANCE_NOTE: 2,
    ReviewTier.OBSERVATION: 3,
}


__all__ = [
    "AssessmentBand",
    "AssessmentGate",
    "EvidenceQuality",
    "EvidenceStrength",
    "ExtractionConfidence",
    "FindingActionStatus",
    "FindingReviewVisibility",
    "FindingTargetType",
    "FindingVisibility",
    "REVIEW_TIER_ORDER",
    "REVIEW_TIERS",
    "RecommendationStatus",
    "ReviewTier",
]
