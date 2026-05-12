from __future__ import annotations

from codeseam.analysis.findings import FindingMetrics


def metric_count(values: dict[str, int] | None, key: str) -> int:
    if values is None:
        return 0
    count = values.get(key, 0)
    return int(count) if isinstance(count, int | float) else 0


def has_relation_pairs(metrics: FindingMetrics) -> bool:
    return metrics.structural_relation_pair_count > 0


def has_structural_duplicates(metrics: FindingMetrics) -> bool:
    return metrics.structural_duplicate_pair_count > 0


def same_language_scope(metrics: FindingMetrics) -> bool:
    return metrics.cluster_scope == "same_language"


__all__ = [
    "has_relation_pairs",
    "has_structural_duplicates",
    "metric_count",
    "same_language_scope",
]
