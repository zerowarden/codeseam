"""Evidence classes mean the members agree, not that a feature is present (REVIEW M7)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from codeseam.analysis import FindingMetrics, RelationPair
from codeseam.analysis.assessment.evidence import (
    EVIDENCE_CALL_FINGERPRINT_OVERLAP,
    EVIDENCE_CONTROL_CONTEXT_SIMILARITY,
    EVIDENCE_LOCAL_DATAFLOW_SIMILARITY,
    evidence_summary,
)


def _pair(*basis: str, call_multiset: float = 0.5) -> RelationPair:
    return cast(
        RelationPair,
        SimpleNamespace(
            clone_classification=SimpleNamespace(basis=basis),
            scores=SimpleNamespace(call_multiset=call_multiset, graph=0.5, parameter_use=0.5),
        ),
    )


@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        (("call_fingerprint_overlap",), EVIDENCE_CALL_FINGERPRINT_OVERLAP),
        (("local_dataflow_similarity",), EVIDENCE_LOCAL_DATAFLOW_SIMILARITY),
        (("control_context_similarity",), EVIDENCE_CONTROL_CONTEXT_SIMILARITY),
    ],
)
def test_pair_agreement_basis_becomes_evidence(basis: tuple[str, ...], expected: str) -> None:
    summary = evidence_summary(
        metrics=FindingMetrics(),
        evidence_kinds=(),
        relation_pairs=(_pair(*basis),),
        has_signature_overlap=False,
    )

    assert summary.has(expected)


def test_partial_similarity_without_agreement_is_not_evidence() -> None:
    summary = evidence_summary(
        metrics=FindingMetrics(),
        evidence_kinds=(),
        relation_pairs=(_pair(call_multiset=0.4),),
        has_signature_overlap=False,
    )

    assert summary.classes == ()
