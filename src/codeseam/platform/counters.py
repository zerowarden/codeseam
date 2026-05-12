from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def increment_stat(stats: dict[str, int] | None, key: str, amount: int = 1) -> None:
    if stats is not None:
        stats[key] = int(stats.get(key, 0)) + amount


def ordered_counts(values: Iterable[object], labels: Iterable[str]) -> dict[str, int]:
    counts = Counter(str(value) for value in values)
    return {label: counts.get(label, 0) for label in labels}


__all__ = ["increment_stat", "ordered_counts"]
