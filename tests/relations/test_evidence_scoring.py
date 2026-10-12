"""Missing evidence is neither agreement nor disagreement (REVIEW M9)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from codeseam.adapters.languages.python.signatures import (
    extract_python_analysis,
    extract_python_relation_detail_source,
)
from codeseam.analysis import MemberFeatureCache, SignatureAnalysis
from codeseam.analysis.relations.actions import pair_actions
from codeseam.analysis.relations.kinds import DeltaKind
from codeseam.analysis.relations.models import SimilarityScores
from codeseam.analysis.relations.pairs import relation_pair_from_features
from codeseam.analysis.relations.scoring import relatedness_score
from codeseam.analysis.signatures import signature_analysis_from_record

NORMALIZE = """def normalize(records):
    cleaned = []
    for record in records:
        cleaned.append(record.strip())
    return cleaned
"""


def _signature(tmp_path: Path, name: str, source: str) -> SignatureAnalysis:
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    record = extract_python_analysis(path, path.name, "source").signatures[0]
    signature = signature_analysis_from_record(record)
    return replace(
        signature,
        core=replace(signature.core, signature_id=name),
        features=extract_python_relation_detail_source(source, name),
    )


@pytest.mark.parametrize(
    ("absent", "expected"),
    [(frozenset(), 0.65), (frozenset({"parameter", "graph"}), 1.0)],
)
def test_relatedness_renormalizes_over_components_with_evidence(
    absent: frozenset[str],
    expected: float,
) -> None:
    scores = SimilarityScores(
        name=1.0, tree=1.0, parameter=0.0, call=1.0, sequence=1.0, graph=0.0, absent=absent
    )

    assert relatedness_score(scores) == expected


def test_unused_parameter_has_no_usage_facts(tmp_path: Path) -> None:
    signature = _signature(tmp_path, "constant", "def constant(x):\n    return 1\n")

    assert not any(dict(signature.features.parameter_features).values())


def test_exact_copy_without_parameter_evidence_is_not_an_argument_flow_change(
    tmp_path: Path,
) -> None:
    left = _signature(tmp_path, "left", NORMALIZE)
    right = _signature(tmp_path, "right", NORMALIZE)
    cache = MemberFeatureCache([left, right])

    pair = relation_pair_from_features(
        cache.get(left),
        cache.get(right),
        action_builder=pair_actions,
    )

    assert pair is not None
    assert DeltaKind.ARGUMENT_FLOW not in pair.delta_kinds
    assert pair.scores.relatedness == 1.0
