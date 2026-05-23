from __future__ import annotations

from typing import Any

from codeseam.analysis import EvidenceKind, RelationKind
from codeseam.platform import as_json_object


def cluster_with_evidence(
    clusters: list[dict[str, Any]],
    evidence_kind: EvidenceKind,
) -> dict[str, Any]:
    return next(item for item in clusters if evidence_kind in item["evidence_kinds"])


def cluster_by_shape(clusters: list[dict[str, Any]], shape: str) -> dict[str, Any]:
    return next(item for item in clusters if item["canonical_shape"] == shape)


def relation_pair_by_kind(cluster: dict[str, Any], kind: RelationKind) -> dict[str, Any]:
    return next(
        pair for pair in cluster["structural_relation_pairs"] if pair["relation_kind"] == kind
    )


def namespace_stats(stats: dict[str, Any], namespace: str) -> dict[str, Any]:
    namespaces = as_json_object(stats.get("namespaces"))
    return as_json_object(namespaces.get(namespace))
