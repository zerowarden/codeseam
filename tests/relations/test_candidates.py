from __future__ import annotations

from collections.abc import Callable

import pytest

from codeseam.analysis import MemberFeatureCache, SignatureAnalysis, candidates

EXPECTED_TRIANGLE_PAIR_COUNT = 3


def _matching_members(
    signature_analysis: Callable[..., SignatureAnalysis],
    *,
    left_hash: str = "sha256:left",
    right_hash: str = "sha256:right",
) -> tuple[SignatureAnalysis, SignatureAnalysis]:
    return (
        signature_analysis(
            "alpha_one",
            statements=("IF", "RETURN:ARG0"),
            body_hash=left_hash,
            arg_reads=((1, ("ARG0",)),),
        ),
        signature_analysis(
            "beta_two",
            statements=("IF", "RETURN:ARG0"),
            body_hash=right_hash,
            arg_reads=((1, ("ARG0",)),),
        ),
    )


def test_lsh_candidate_pairs_surface_structural_matches_without_bucket_overlap(
    force_lsh: Callable[[], None],
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    force_lsh()
    left, right = _matching_members(signature_analysis)

    pairs = candidates.relation_candidate_pairs([left, right], MemberFeatureCache([left, right]))

    assert pairs == [(left, right)]


def test_exact_body_hash_pairs_do_not_depend_on_lsh(
    monkeypatch: pytest.MonkeyPatch,
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    monkeypatch.setattr(candidates, "LSH_CLUSTER_MEMBER_THRESHOLD", 99)
    left, _ = _matching_members(
        signature_analysis,
        left_hash="sha256:shared",
        right_hash="sha256:shared",
    )
    right = signature_analysis(
        "beta_two",
        statements=("TRY", "RAISE"),
        body_hash="sha256:shared",
    )

    pairs = candidates.relation_candidate_pairs([left, right], MemberFeatureCache([left, right]))

    assert pairs == [(left, right)]


def test_lsh_is_disabled_without_deterministic_pair_cap_pressure(
    monkeypatch: pytest.MonkeyPatch,
    force_lsh_collision: Callable[[], None],
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    monkeypatch.setattr(candidates, "LSH_CLUSTER_MEMBER_THRESHOLD", 2)
    force_lsh_collision()
    left, right = _matching_members(signature_analysis)

    pairs = candidates.relation_candidate_pairs([left, right], MemberFeatureCache([left, right]))

    assert pairs == []


def test_lsh_collision_requires_exact_similarity_verification(
    force_lsh: Callable[[], None],
    force_lsh_collision: Callable[[], None],
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    force_lsh()
    force_lsh_collision()
    left = signature_analysis(
        "alpha_one",
        statements=("IF", "RETURN:ARG0"),
        body_hash="sha256:left",
        arg_reads=((1, ("ARG0",)),),
    )
    right = signature_analysis(
        "zeta_two",
        statements=("TRY", "RAISE"),
        body_hash="sha256:right",
        file="src/zeta.py",
    )

    pairs = candidates.relation_candidate_pairs([left, right], MemberFeatureCache([left, right]))

    assert pairs == []


def test_lsh_bucket_overflow_uses_fallback_by_skipping_noisy_bucket(
    monkeypatch: pytest.MonkeyPatch,
    force_lsh: Callable[[], None],
    force_lsh_collision: Callable[[], None],
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    force_lsh()
    monkeypatch.setattr(candidates, "LSH_MAX_BUCKET_MEMBER_COUNT", 1)
    force_lsh_collision()
    members = _matching_members(
        signature_analysis,
        left_hash="sha256:shared",
        right_hash="sha256:shared",
    )

    pairs = candidates.relation_candidate_pairs(list(members), MemberFeatureCache(members))

    assert pairs == [(members[0], members[1])]


def test_lsh_candidate_pairs_are_deterministic_for_equivalent_large_clusters(
    force_lsh: Callable[[], None],
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    force_lsh()
    members = (
        signature_analysis(
            "alpha_one",
            statements=("TRY", "ASSIGN:CALL:encode", "RETURN:ARG0"),
            body_hash="sha256:alpha",
            arg_reads=((1, ("ARG0",)), (2, ("ARG0",))),
            file="src/a.py",
        ),
        signature_analysis(
            "beta_two",
            statements=("TRY", "ASSIGN:CALL:encode", "RETURN:ARG0"),
            body_hash="sha256:beta",
            arg_reads=((1, ("ARG0",)), (2, ("ARG0",))),
            file="src/b.py",
        ),
        signature_analysis(
            "gamma_three",
            statements=("TRY", "ASSIGN:CALL:encode", "RETURN:ARG0"),
            body_hash="sha256:gamma",
            arg_reads=((1, ("ARG0",)), (2, ("ARG0",))),
            file="src/c.py",
        ),
    )
    cache = MemberFeatureCache(members)

    first = candidates.relation_candidate_pairs(list(members), cache)
    second = candidates.relation_candidate_pairs(list(reversed(members)), cache)

    assert first == second
    assert len(first) == EXPECTED_TRIANGLE_PAIR_COUNT
