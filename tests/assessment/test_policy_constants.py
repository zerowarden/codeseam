from __future__ import annotations

from codeseam.analysis import PolicyConstant, build_policy_constant_clusters


def test_policy_constant_confidence_is_derived_from_evidence() -> None:
    [cluster] = build_policy_constant_clusters(
        [
            _constant("src/a.py", role="source"),
            _constant("src/b.py", role="source"),
        ]
    )

    assert 0.0 < cluster.confidence < 1.0
    assert cluster.refactor_action_candidates[0].confidence == cluster.confidence


def test_policy_constant_action_confidence_accounts_for_ownership() -> None:
    [cluster] = build_policy_constant_clusters(
        [
            _constant("src/a.py", role="source"),
            _constant("tests/b.py", role="test"),
        ]
    )

    assert 0.0 < cluster.confidence < 1.0
    assert cluster.refactor_action_candidates[0].confidence < cluster.confidence


def _constant(path: str, *, role: str) -> PolicyConstant:
    return PolicyConstant(
        language="python",
        file=path,
        symbol="PRIORITY_ORDER",
        normalized_symbol="priority order",
        start_line=1,
        end_line=3,
        role=role,
        literal_kind="Tuple",
        literal_shape_hash="shape:priority",
        literal_preview="('high', 'medium', 'low')",
    )
