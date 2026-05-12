from __future__ import annotations

from collections.abc import Iterable

from codeseam.analysis.assessment.definitions import REVIEW_TIERS
from codeseam.platform import ordered_counts


def review_tier_counts(tiers: Iterable[object]) -> dict[str, int]:
    return ordered_counts(tiers, REVIEW_TIERS)
