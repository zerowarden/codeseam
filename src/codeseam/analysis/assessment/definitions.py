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
    SIGNATURE_ONLY = "signature_only"


class RecommendationStatus(StrEnum):
    RECOMMENDED = "recommended"
    CAUTIOUS = "cautious"
    NOT_RECOMMENDED = "not_recommended"


__all__ = [
    "AssessmentBand",
    "AssessmentGate",
    "EvidenceQuality",
    "RecommendationStatus",
]
