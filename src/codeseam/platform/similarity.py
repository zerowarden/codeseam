from __future__ import annotations

from collections import Counter
from collections.abc import Mapping


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 4)


def counter_jaccard(left: Counter[str], right: Counter[str]) -> float:
    if not left and not right:
        return 0.0
    keys = set(left) | set(right)
    overlap = sum(min(left[key], right[key]) for key in keys)
    total = sum(max(left[key], right[key]) for key in keys)
    return round(overlap / total, 4) if total else 0.0


def mean_jaccard_by_key(
    left: Mapping[str, set[str]],
    right: Mapping[str, set[str]],
) -> float:
    keys = sorted(set(left) | set(right))
    if not keys:
        return 0.0
    return round(
        sum(jaccard(left.get(key, set()), right.get(key, set())) for key in keys) / len(keys),
        4,
    )
