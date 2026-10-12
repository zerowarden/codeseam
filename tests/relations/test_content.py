from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import file_record

from codeseam.adapters.languages import default_language_registry
from codeseam.adapters.languages.extraction import analyze_language_file, language_context
from codeseam.analysis import SignatureAnalysis, build_clusters, candidates
from codeseam.analysis.relations import content
from codeseam.analysis.relations.content import ContentEdge, content_components, member_key
from codeseam.analysis.relations.policy import CONTENT_POLICY

STATEMENTS = ("ASSIGN:CALL", "IF", "EXPR:CALL", "RETURN:ARG0")
CALLS = ("load.read", "parse.decode", "store.write", "log.info")

type Build = Callable[..., SignatureAnalysis]


def _member(  # noqa: PLR0913
    build: Build,
    symbol: str,
    *,
    statements: tuple[str, ...] = STATEMENTS,
    calls: tuple[str, ...] = CALLS,
    body_hash: str | None = None,
    role: str = "source",
) -> SignatureAnalysis:
    return build(
        symbol,
        statements=statements,
        calls=calls,
        body_hash=body_hash or f"sha256:{symbol}",
        file=f"src/{symbol}.py",
        role=role,
    )


def _edges(components: list[list[ContentEdge]]) -> list[tuple[str, str]]:
    return sorted(
        (left.core.symbol, right.core.symbol) for group in components for left, right in group
    )


@pytest.mark.parametrize(
    ("right_calls", "right_hash", "paired"),
    [
        (CALLS, "sha256:left", True),
        ((*CALLS[:3], "audit.emit"), None, True),
        (("a.x", "b.y", "c.z", "d.w"), None, False),
    ],
    ids=["identical-body", "shared-rare-content", "same-statements-only"],
)
def test_content_pairs_need_an_identical_body_or_overlapping_rare_content(
    signature_analysis: Build,
    right_calls: tuple[str, ...],
    right_hash: str | None,
    paired: bool,
) -> None:
    members = [
        _member(signature_analysis, "left", body_hash="sha256:left"),
        _member(signature_analysis, "right", calls=right_calls, body_hash=right_hash),
    ]

    assert _edges(content_components(members, seen=set())) == (
        [("left", "right")] if paired else []
    )


def test_one_statement_bodies_never_pair_across_signatures(signature_analysis: Build) -> None:
    members = [
        _member(signature_analysis, name, statements=("RETURN:CALL",), body_hash="sha256:same")
        for name in ("left", "right")
    ]

    assert content_components(members, seen=set()) == []


@pytest.mark.parametrize(
    ("already_compared", "right_role", "split_test", "paired"),
    [
        (True, "source", True, False),
        (False, "test", True, False),
        (False, "test", False, True),
    ],
    ids=["seen-pair", "split-test-source", "mixed-allowed"],
)
def test_content_pairs_skip_compared_and_test_source_pairs(
    signature_analysis: Build,
    already_compared: bool,
    right_role: str,
    split_test: bool,
    paired: bool,
) -> None:
    left = _member(signature_analysis, "left", body_hash="sha256:same")
    right = _member(signature_analysis, "right", body_hash="sha256:same", role=right_role)
    seen = {frozenset((member_key(left), member_key(right)))} if already_compared else set()

    edges = _edges(content_components([left, right], seen=seen, split_test=split_test))

    assert edges == ([("left", "right")] if paired else [])


@pytest.mark.parametrize(("member_count", "edge_count"), [(2, 1), (3, 0)])
def test_shingles_shared_too_widely_do_not_block(
    signature_analysis: Build,
    monkeypatch: pytest.MonkeyPatch,
    member_count: int,
    edge_count: int,
) -> None:
    monkeypatch.setattr(content, "CONTENT_POLICY", replace(CONTENT_POLICY, rare_shingle_max_df=2))
    members = [_member(signature_analysis, f"fn_{index}") for index in range(member_count)]

    assert len(_edges(content_components(members, seen=set()))) == edge_count


def test_content_components_stay_within_the_member_limit(
    signature_analysis: Build,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        content, "CONTENT_POLICY", replace(CONTENT_POLICY, component_member_limit=2)
    )
    members = [
        _member(signature_analysis, f"fn_{index}", body_hash="sha256:same") for index in range(3)
    ]

    components = content_components(members, seen=set())

    assert components
    assert all(
        len({member_key(member) for edge in group for member in edge}) <= 2  # noqa: PLR2004
        for group in components
    )


def test_near_duplicates_above_the_bucket_size_limit_are_compared(
    signature_analysis: Build,
) -> None:
    body = ("ASSIGN:CALL", "IF", "EXPR:CALL", "FOR", "ASSIGN:Assign", "TRY") * 2
    left, right = (
        _member(signature_analysis, symbol, statements=statements, calls=calls)
        for symbol, statements, calls in (
            ("export_users", (*body, "RETURN:ARG0"), CALLS),
            ("export_orders", (*body, "EXPR:CALL", "RETURN:ARG0"), (*CALLS, "audit.emit")),
        )
    )

    assert candidates.relation_candidate_members([left, right]) == []
    (cluster,) = [
        cluster
        for cluster in build_clusters([left, right])
        if cluster.review_relevance == "content_similarity"
    ]
    assert cluster.enrichment is not None
    assert len(cluster.enrichment.structural_relation_pairs) == 1


DIVERGENT_SIGNATURES = """
def collect_thread_errors(config, key):
    pop = config.stash[key].pop
    errors = []
    while True:
        try:
            meta = pop()
        except IndexError:
            break
        if isinstance(meta, BaseException):
            errors.append(RuntimeError("hook failed"))
            continue
        errors.append(meta.warning)
    if errors:
        raise ExceptionGroup("thread errors", errors)


def collect_unraisable(config):
    pop = config.stash["unraisable"].pop
    errors = []
    while True:
        try:
            meta = pop()
        except IndexError:
            break
        if isinstance(meta, BaseException):
            errors.append(RuntimeError("hook failed"))
            continue
        errors.append(meta.message)
    if errors:
        raise ExceptionGroup("unraisable", errors)
"""


def test_similar_functions_with_different_signatures_form_a_content_cluster(
    tmp_path: Path,
) -> None:
    (tmp_path / "hooks.py").write_text(DIVERGENT_SIGNATURES, encoding="utf-8")
    record = file_record("hooks.py", language="Python")
    result = analyze_language_file(
        language_context(tmp_path, "hooks.py", record), record, default_language_registry(), None
    )

    (cluster,) = [
        cluster
        for cluster in build_clusters(result.signatures)
        if cluster.review_relevance == "content_similarity"
    ]

    assert {member.signature.symbol for member in cluster.members} == {
        "collect_thread_errors",
        "collect_unraisable",
    }
    assert cluster.canonical_shape.startswith("content_similarity(")
    assert cluster.enrichment is not None
    assert cluster.enrichment.structural_relation_pairs
