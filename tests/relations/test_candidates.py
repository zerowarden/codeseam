from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from codeseam.analysis import MemberFeatureCache, SignatureAnalysis, build_clusters, candidates
from codeseam.analysis.relations.policy import STRUCTURAL_POLICY

EXPECTED_TRIANGLE_PAIR_COUNT = 3
EXPECTED_TRUNCATED_PAIRS = 2
LARGE_CLUSTER_MEMBER_COUNT = 90
SIX_STATEMENTS = ("ASSIGN:CALL", "IF", "ASSIGN:CALL", "EXPR:CALL", "ASSIGN:Assign", "RETURN:ARG0")


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


def test_exact_body_hash_pairs_need_no_shared_name_or_call(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    left, _ = _matching_members(signature_analysis, left_hash="sha256:shared")
    right = signature_analysis("beta_two", statements=("TRY", "RAISE"), body_hash="sha256:shared")

    pairs = candidates.relation_candidate_pairs([left, right], MemberFeatureCache([left, right]))

    assert pairs == [(left, right)]


def test_candidate_pairs_are_deterministic_for_reordered_members(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    members = tuple(
        signature_analysis(
            symbol,
            statements=("TRY", "ASSIGN:CALL", "RETURN:ARG0"),
            calls=("codec.encode",),
            body_hash=f"sha256:{symbol}",
            file=f"src/{symbol}.py",
        )
        for symbol in ("alpha_one", "beta_two", "gamma_three")
    )
    cache = MemberFeatureCache(members)

    first = candidates.relation_candidate_pairs(list(members), cache)
    second = candidates.relation_candidate_pairs(list(reversed(members)), cache)

    assert first == second
    assert len(first) == EXPECTED_TRIANGLE_PAIR_COUNT


def test_large_clusters_keep_every_member_regardless_of_size(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    small = [
        signature_analysis(f"tiny_{index}", body_hash=f"sha256:{index}", file=f"src/t{index}.py")
        for index in range(LARGE_CLUSTER_MEMBER_COUNT)
    ]
    clones = [
        signature_analysis(symbol, statements=SIX_STATEMENTS, body_hash="sha256:clone", file=file)
        for symbol, file in (("render_a", "src/z1.py"), ("render_b", "src/z2.py"))
    ]
    members = [*small, *clones]
    cache = MemberFeatureCache(members)

    eligible = candidates.relation_candidate_members(members, cache)

    assert len(eligible) == len(members)
    assert (clones[0], clones[1]) in candidates.relation_candidate_pairs(eligible, cache)


def test_pair_limit_keeps_similar_content_over_shared_names_and_counts_the_cut(
    signature_analysis: Callable[..., SignatureAnalysis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        candidates,
        "STRUCTURAL_POLICY",
        replace(STRUCTURAL_POLICY, structural_pair_candidate_limit=1),
    )
    near = ("IF", "ASSIGN:CALL", "RETURN:ARG0")
    left, right, namesake = (
        signature_analysis(
            symbol, statements=statements, calls=calls, body_hash=f"sha256:{file}", file=file
        )
        for symbol, statements, calls, file in (
            ("load_user", near, ("cache.read", "codec.decode"), "src/a.py"),
            ("fetch_user", near, ("cache.read", "codec.decode", "log.debug"), "src/b.py"),
            ("load_user", ("TRY", "RAISE"), ("cache.read",), "src/c.py"),
        )
    )
    stats: dict[str, int] = {}

    pairs = candidates.relation_candidate_pairs([left, right, namesake], None, stats)

    assert pairs == [(left, right)]
    assert stats["candidate_pairs_truncated_count"] == EXPECTED_TRUNCATED_PAIRS


def test_bucket_member_limit_is_counted(
    signature_analysis: Callable[..., SignatureAnalysis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        candidates,
        "STRUCTURAL_POLICY",
        replace(STRUCTURAL_POLICY, structural_bucket_member_limit=2),
    )
    first, second, third = (
        signature_analysis(symbol, body_hash="sha256:same", file=f"src/{symbol}.py")
        for symbol in ("alpha", "beta", "gamma")
    )
    stats: dict[str, int] = {}

    pairs = candidates.relation_candidate_pairs([third, second, first], None, stats)

    assert pairs == [(first, second)]
    assert stats["candidate_bucket_members_truncated_count"] == 1


@pytest.mark.parametrize(
    ("statement_count", "expected_pairs"),
    [(8, 0), (9, 1), (40, 1)],
)
def test_oversized_identical_bodies_are_paired_regardless_of_size(
    signature_analysis: Callable[..., SignatureAnalysis],
    statement_count: int,
    expected_pairs: int,
) -> None:
    statements = ("ASSIGN:Assign",) * (statement_count - 1) + ("RETURN:",)
    left, right = (
        signature_analysis(symbol, statements=statements, body_hash="sha256:same", file=file)
        for symbol, file in (("build_report", "src/a.py"), ("build_summary", "src/b.py"))
    )

    pairs = candidates.oversized_exact_body_pairs([left, right], MemberFeatureCache([left, right]))

    assert len(pairs) == expected_pairs


def test_oversized_bodies_with_different_hashes_are_not_paired(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    statements = ("ASSIGN:Assign",) * 20 + ("RETURN:",)
    left = signature_analysis("left", statements=statements, body_hash="sha256:a")
    right = signature_analysis("right", statements=statements, body_hash="sha256:b")

    assert candidates.oversized_exact_body_pairs([left, right]) == []


def test_cluster_enrichment_reports_oversized_identical_bodies(
    signature_analysis: Callable[..., SignatureAnalysis],
) -> None:
    statements = ("ASSIGN:Assign",) * 20 + ("RETURN:",)
    members = [
        signature_analysis(symbol, statements=statements, body_hash="sha256:same", file=file)
        for symbol, file in (("build_report", "src/a.py"), ("build_summary", "src/b.py"))
    ]

    (cluster,) = build_clusters(members)

    assert cluster.enrichment is not None
    (pair,) = cluster.enrichment.structural_relation_pairs
    assert pair.flags.body_hash_match
