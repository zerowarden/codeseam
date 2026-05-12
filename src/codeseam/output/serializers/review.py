from __future__ import annotations

from codeseam.analysis import REVIEW_TIERS, review_tier_counts
from codeseam.platform import Json, as_json_objects, json_text


def review_tier(item: Json) -> str:
    value = json_text(item, "review_tier")
    if value in REVIEW_TIERS:
        return value
    return REVIEW_TIERS[-1]


def target_review_tier(target: Json) -> str:
    return review_tier(target)


def target_review_tier_counts(targets: list[Json]) -> dict[str, int]:
    return review_tier_counts(review_tier(target) for target in targets)


def targets_with_review_tiers(targets: object, tiers: set[str]) -> list[Json]:
    return [target for target in as_json_objects(targets) if review_tier(target) in tiers]
