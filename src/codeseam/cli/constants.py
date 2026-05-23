from __future__ import annotations

from codeseam.analysis import ReviewTier

ANALYZE_FORMATS = ("json", "ndjson", "sarif")
DEFAULT_PAIR_LIMIT = 3
DEFAULT_TARGET_LIMIT = 50
REVIEW_TIER_LABELS = {
    ReviewTier.RECOMMENDED_EDIT: "recommended edits",
    ReviewTier.REVIEW_CANDIDATE: "review required",
    ReviewTier.MAINTENANCE_NOTE: "maintenance notes",
    ReviewTier.OBSERVATION: "observations",
}


__all__ = [
    "ANALYZE_FORMATS",
    "DEFAULT_PAIR_LIMIT",
    "DEFAULT_TARGET_LIMIT",
    "REVIEW_TIER_LABELS",
]
