"""Enums that describe a finding: its tier, action status, visibility and type."""

from __future__ import annotations

from enum import StrEnum


class EvidenceStrength(StrEnum):
    NONE = ""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


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
    "REVIEW_TIER_ORDER",
    "REVIEW_TIERS",
    "EvidenceStrength",
    "FindingActionStatus",
    "FindingReviewVisibility",
    "FindingTargetType",
    "ReviewTier",
]
