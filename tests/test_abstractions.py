from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

from codeseam.analysis import (
    TREE_EDIT_POLICY,
    AdapterId,
    CachedRelationSummary,
    DataflowGraph,
    LanguageFamily,
    MemberFeatureCache,
    MemberFeatures,
    OrderedTree,
    RelationMember,
    RelationPair,
    SignatureAnalysis,
    SignatureCore,
    SignatureOutputDetail,
    SignatureTypeSource,
    SimilarityScores,
    TreeComparison,
    ordered_tree_size,
    pair_actions,
    pairs,
    signature_analysis_from_core,
    similarity,
)
from codeseam.cache import AnalysisCacheContext, LanguageRunCache, persistent_cache
from codeseam.cache import relation_cache as relation_pair_cache

EXPECTED_TREE_SIMILARITY = 0.5
EXPECTED_TREE_NODE_COUNT = 2
EXPECTED_TREE_EDIT_BUDGET_OVERFLOW = 2
INVALID_CACHE_VALUES = (None, b"not-a-cache-blob", {"result": "unknown"}, "bad")


@dataclass(frozen=True)
class TreeComparisonGuardCase:
    left: dict[str, Any]
    right: dict[str, Any]
    expected_source: str


@dataclass(frozen=True)
class NameSimilarityCase:
    left: str
    right: str
    expected: float
    expected_similarity_calls: int = 0


def test_tree_comparison_computes_edit_distance_once(monkeypatch: pytest.MonkeyPatch) -> None:
    def assert_module(left: OrderedTree, right: OrderedTree) -> int:
        assert left.label == "Module"
        assert right.label == "Module"
        return 1

    distance_calls = _patch_tree_distance(monkeypatch, assert_module)
    left = _features(
        "fn_left",
        body_tree=OrderedTree("Module", (OrderedTree("Return"),)),
        body_shape="module return",
        body_hash="",
    )
    right = _features(
        "fn_right",
        body_tree=OrderedTree("Module", (OrderedTree("Raise"),)),
        body_shape="module raise",
        body_hash="",
    )

    result = similarity.tree_comparison_features(left, right)

    assert distance_calls() == 1
    assert result.tree_edit_distance == 1
    assert result.tree_similarity == EXPECTED_TREE_SIMILARITY


def test_tree_comparison_skips_edit_distance_when_product_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distance_calls = _patch_tree_distance(monkeypatch, lambda _left, _right: 1)
    left_tree = _wide_tree(150)
    right_tree = _wide_tree(150)
    left = _features("fn_left", body_tree=left_tree, body_shape="module left", body_hash="")
    right = _features("fn_right", body_tree=right_tree, body_shape="module right", body_hash="")

    result = similarity.tree_comparison_features(left, right)

    assert distance_calls() == 0
    assert result.tree_edit_distance is None
    assert result.tree_distance_source == similarity.TREE_EDIT_PRODUCT_LIMIT_SOURCE


@pytest.mark.parametrize(
    "case",
    [
        TreeComparisonGuardCase(
            left={
                "body_shape": "CALL:a " * 200,
                "body_hash": "sha256:left",
                "statements": ("CALL:a", "RETURN:x"),
            },
            right={
                "body_shape": "CALL:b " * 200,
                "body_hash": "sha256:right",
                "statements": ("CALL:b", "RETURN:y"),
            },
            expected_source=similarity.BODY_SHAPE_TEXT_PRODUCT_LIMIT_SOURCE,
        ),
        TreeComparisonGuardCase(
            left={
                "tree_node_count": 3,
                "body_shape": "",
                "body_hash": "shape32:left",
                "statements": ("CALL:format", "RETURN:ARG0"),
            },
            right={
                "tree_node_count": 3,
                "body_shape": "",
                "body_hash": "shape32:right",
                "statements": ("CALL:format", "RETURN:ARG0"),
            },
            expected_source=similarity.BODY_SHAPE_LAZY_PROXY_SOURCE,
        ),
    ],
    ids=lambda case: case.expected_source,
)
def test_tree_comparison_uses_guardrails_before_expensive_similarity(
    monkeypatch: pytest.MonkeyPatch,
    case: TreeComparisonGuardCase,
) -> None:
    monkeypatch.setattr(similarity, "similarity_ratio", _fail_similarity)
    left = _features("fn_left", **case.left)
    right = _features("fn_right", **case.right)

    result = similarity.tree_comparison_features(left, right)

    assert result.tree_edit_distance is None
    assert result.tree_distance_source == case.expected_source


def test_tree_comparison_cache_reuses_lower_level_fact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def fake_comparison(left: object, right: object) -> TreeComparison:
        nonlocal calls
        calls += 1
        return TreeComparison(0.75, 0.25, 1, 4, "ordered_tree_edit_distance")

    monkeypatch.setattr(relation_pair_cache, "tree_comparison_features", fake_comparison)
    cache = persistent_cache(tmp_path / ".cache" / "codeseam", enabled=True)
    try:
        caches = AnalysisCacheContext(
            persistent=cache,
            file_analysis_enabled=True,
            relation_pair_enabled=True,
            language=LanguageRunCache(),
        )
        left = _member("fn_left")
        right = _member("fn_right")
        feature_cache = MemberFeatureCache([left, right])
        stats: dict[str, int] = {}
        provider = relation_pair_cache.cached_tree_comparison_provider(caches, stats)

        first = provider(feature_cache.get(left), feature_cache.get(right))
        second = provider(feature_cache.get(left), feature_cache.get(right))

        assert calls == 1
        assert first == second
        assert stats["tree_comparison_cache_miss_count"] == 1
        assert stats["tree_comparison_cache_hit_count"] == 1
    finally:
        cache.close()


def test_member_feature_cache_reuses_features_for_same_member() -> None:
    member = _member("fn_1", symbol="example", body_hash="sha256:body")
    cache = MemberFeatureCache([member])

    assert cache.get(member) is cache.get(member)
    assert cache.get(member).tree_node_count == EXPECTED_TREE_NODE_COUNT


def test_relation_pair_cache_key_uses_hydrated_member_digest() -> None:
    left = _member("fn_left")
    right = _member("fn_right")
    cache = MemberFeatureCache([left, right])

    left_features = cache.get(left)
    right_features = cache.get(right)
    first = relation_pair_cache.relation_pair_cache_key(left_features, right_features)
    second = relation_pair_cache.relation_pair_cache_key(left_features, right_features)

    assert first == second
    assert left_features.member.digest in first
    assert right_features.member.digest in first


def test_member_digest_includes_semantic_roles() -> None:
    ordinary = _member("fn_left")
    guarded = _member(
        "fn_left",
        semantic_roles=("declaration_boundary",),
        semantic_role_reasons=("declaration signatures describe API shape",),
    )

    assert (
        RelationMember.from_signature(ordinary).digest
        != RelationMember.from_signature(guarded).digest
    )


def test_relation_pair_group_cache_stores_compact_summaries() -> None:
    left = _member("fn_left")
    right = _member("fn_right")
    cache = MemberFeatureCache([left, right])
    left_features = cache.get(left)
    right_features = cache.get(right)
    pair = pairs.relation_pair_from_features(
        left_features,
        right_features,
        action_builder=pair_actions,
    )
    assert pair is not None

    value = relation_pair_cache.relation_pair_group_cache_value([pair])
    summaries = value["pairs"]

    assert isinstance(summaries, tuple)
    assert isinstance(summaries[0], CachedRelationSummary)
    assert not isinstance(summaries[0], RelationPair)

    cached, restored = relation_pair_cache.relation_pairs_from_group_cache_value(
        value,
        {
            relation_pair_cache.relation_pair_ref_cache_key(pair.left, pair.right): (
                left_features,
                right_features,
            )
        },
    )
    assert cached is True
    assert restored[0].relation_kind == pair.relation_kind
    assert restored[0].scores.relatedness == pair.scores.relatedness


def test_relation_pair_group_cache_handles_legacy_summary_slots() -> None:
    left = _member("fn_left")
    right = _member("fn_right")
    cache = MemberFeatureCache([left, right])
    left_features = cache.get(left)
    right_features = cache.get(right)
    pair = pairs.relation_pair_from_features(
        left_features,
        right_features,
        action_builder=pair_actions,
    )
    assert pair is not None
    value = relation_pair_cache.relation_pair_group_cache_value([pair])
    summaries = cast(tuple[CachedRelationSummary, ...], value["pairs"])
    summary = summaries[0]
    legacy_summary = replace(
        summary,
        min_body_line_count=cast(Any, pair.refactor_action_candidates),
    )

    cached, restored = relation_pair_cache.relation_pairs_from_group_cache_value(
        {**value, "pairs": (legacy_summary,)},
        {
            relation_pair_cache.relation_pair_ref_cache_key(pair.left, pair.right): (
                left_features,
                right_features,
            )
        },
    )

    assert cached is True
    assert restored[0].min_body_line_count == min(
        left_features.body_line_count,
        right_features.body_line_count,
    )


@pytest.mark.parametrize("cached", INVALID_CACHE_VALUES)
def test_relation_pair_cache_rejects_invalid_values(cached: object) -> None:
    assert relation_pair_cache.relation_pair_from_cache_value(cached) == (False, None)
    assert relation_pair_cache.relation_pairs_from_group_cache_value(cached, {}) == (False, ())


def test_tree_comparison_cache_value_round_trips() -> None:
    tree = TreeComparison(0.75, 0.25, 1, 4, "ordered_tree_edit_distance")

    cached, restored = relation_pair_cache.tree_comparison_from_cache_value(
        relation_pair_cache.tree_comparison_cache_value(tree)
    )

    assert cached is True
    assert restored == tree


def test_tree_edit_decision_skips_when_cheap_evidence_is_sufficient() -> None:
    left = _member("fn_left", statements=("CALL:a", "RETURN:x"))
    right = _member("fn_right", statements=("CALL:b", "RETURN:y"))
    cache = MemberFeatureCache([left, right])

    decision = pairs.tree_edit_decision(
        cache.get(left),
        cache.get(right),
        SimilarityScores(name=0.2, tree=0.0, sequence=0.5, parameter=0.8, call=0.4, graph=0.4),
        has_argument_normalization=False,
    )

    assert decision.compare_edit_distance is False
    assert decision.reject is False
    assert decision.tree_distance_source == "tree_edit_skipped_cheap_evidence_sufficient"


def test_tree_edit_decision_skips_when_edit_product_limit_is_exceeded() -> None:
    left = _features("fn_left", body_tree=_wide_tree(150))
    right = _features("fn_right", body_tree=_wide_tree(150))

    decision = pairs.tree_edit_decision(
        left,
        right,
        SimilarityScores(name=0.9, tree=0.0, sequence=0.8, parameter=0.8, call=0.8, graph=0.8),
        has_argument_normalization=False,
    )

    assert decision.compare_edit_distance is False
    assert decision.reject is False
    assert decision.tree_distance_source == similarity.TREE_EDIT_PRODUCT_LIMIT_SOURCE


def test_tree_edit_decision_rejects_when_tree_cannot_make_pair_relevant() -> None:
    left = _member("fn_left")
    right = _member("fn_right")
    cache = MemberFeatureCache([left, right])

    decision = pairs.tree_edit_decision(
        cache.get(left),
        cache.get(right),
        SimilarityScores(name=0.0, tree=0.0, sequence=0.0, parameter=0.0, call=0.0, graph=0.0),
        has_argument_normalization=False,
    )

    assert decision.compare_edit_distance is False
    assert decision.reject is True
    assert decision.tree_distance_source == "pre_tree_best_possible_below_threshold"


@pytest.mark.parametrize(
    "case",
    [
        NameSimilarityCase("parse config", "write output", 0.0),
        NameSimilarityCase("short", "very long unrelated name", 0.0),
        NameSimilarityCase("load suppressions", "load settings", round(1 / 3, 4)),
        NameSimilarityCase(
            "parse config",
            "parse configs",
            EXPECTED_TREE_SIMILARITY,
            expected_similarity_calls=1,
        ),
    ],
    ids=lambda case: f"{case.left}->{case.right}",
)
def test_name_similarity_gate(monkeypatch: pytest.MonkeyPatch, case: NameSimilarityCase) -> None:
    pairs._name_similarity.cache_clear()
    calls: list[tuple[str, str]] = []

    def fake_similarity(left: str, right: str) -> float:
        calls.append((left, right))
        return EXPECTED_TREE_SIMILARITY

    monkeypatch.setattr(pairs, "similarity_ratio", fake_similarity)

    assert pairs._name_similarity(case.left, case.right) == case.expected
    assert len(calls) == case.expected_similarity_calls
    if case.expected_similarity_calls:
        assert calls == [(case.left, case.right)]


def test_relation_pair_tree_edit_uses_cluster_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    distance_calls = _patch_tree_distance(
        monkeypatch,
        lambda left, right: 0 if left.label == right.label else 1,
    )
    stats: dict[str, int] = {}

    for index in range(TREE_EDIT_POLICY.cluster_budget + EXPECTED_TREE_EDIT_BUDGET_OVERFLOW):
        left = _features(
            f"fn_left_{index}",
            symbol="shared",
            body_tree=OrderedTree("Module", (OrderedTree("Return"),)),
            body_hash=f"sha256:left:{index}",
        )
        right = _features(
            f"fn_right_{index}",
            symbol="shared",
            body_tree=OrderedTree("Module", (OrderedTree("Raise"),)),
            body_hash=f"sha256:right:{index}",
        )

        pair = pairs.relation_pair_from_features(
            left,
            right,
            action_builder=pair_actions,
            stats=stats,
        )

        assert pair is not None

    assert distance_calls() == TREE_EDIT_POLICY.cluster_budget
    assert stats["tree_edit_requested_count"] == TREE_EDIT_POLICY.cluster_budget
    assert stats["tree_edit_budget_exhausted_count"] == EXPECTED_TREE_EDIT_BUDGET_OVERFLOW


def _member(  # noqa: PLR0913
    function_id: str,
    *,
    symbol: str | None = None,
    body_hash: str | None = None,
    tree_node_count: int = EXPECTED_TREE_NODE_COUNT,
    statements: tuple[str, ...] = ("RETURN:ARG0",),
    semantic_roles: tuple[str, ...] = (),
    semantic_role_reasons: tuple[str, ...] = (),
) -> SignatureAnalysis:
    core = SignatureCore(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.UNKNOWN,
        file="src/example.py",
        symbol=symbol or function_id,
        normalized_symbol=symbol or function_id,
        container=None,
        start_line=1,
        end_line=2,
        role="function",
        type_source=SignatureTypeSource.INFERRED,
        parameters=("arg0",),
        return_type="object",
        canonical_shape="fn(arg0)->object",
        shape_hash=f"shape:{function_id}",
        body_line_count=max(1, len(statements)),
        body_shape_hash=body_hash or f"sha256:{function_id}",
        body_tree_node_count=tree_node_count,
        statement_sequence=statements,
        return_signature=tuple(item for item in statements if item.startswith("RETURN:")),
        signature_id=f"sig_{function_id}",
        function_id=function_id,
        semantic_roles=semantic_roles,
        semantic_role_reasons=semantic_role_reasons,
    )
    return signature_analysis_from_core(
        core,
        output=SignatureOutputDetail(
            signature_id=core.signature_id,
            body_shape="module return",
        ),
    )


def _features(  # noqa: PLR0913
    function_id: str,
    *,
    symbol: str | None = None,
    body_tree: OrderedTree | None = None,
    body_shape: str = "module return",
    body_hash: str | None = None,
    tree_node_count: int | None = None,
    statements: tuple[str, ...] = ("RETURN:ARG0",),
) -> MemberFeatures:
    node_count = tree_node_count or EXPECTED_TREE_NODE_COUNT
    signature = _member(
        function_id,
        symbol=symbol,
        body_hash=body_hash,
        tree_node_count=node_count,
        statements=statements,
    )
    relation_member = replace(
        RelationMember.from_signature(signature),
        body_shape=body_shape,
        body_tree=body_tree,
        body_tree_node_count=ordered_tree_size(body_tree) if body_tree else node_count,
    )
    return MemberFeatures(
        key=(function_id, "feature"),
        member=relation_member,
        body_hash=relation_member.body_shape_hash,
        body_shape=relation_member.body_shape,
        body_tree_payload=body_tree,
        tree_node_count=relation_member.body_tree_node_count,
        normalized_name=symbol or function_id,
        role="function",
        statements=statements,
        statement_fingerprint=hash(statements),
        calls=(),
        call_set=frozenset(),
        call_fingerprints=(),
        call_counts=Counter(),
        parameter_default_roles={},
        parameter_vectors={},
        local_dataflow_graph=DataflowGraph(),
        graph_features=frozenset(),
        literal_shapes=frozenset(),
        receiver_shapes=frozenset(),
        parameter_features={},
        normalization_transform_tokens=frozenset(),
        statement_arg_reads=(),
        control_vector=(),
        control_set=frozenset(),
        return_signature=tuple(item for item in statements if item.startswith("RETURN:")),
        error_shape=((), 0, 0),
        body_line_count=max(1, len(statements)),
    )


def _wide_tree(node_count: int) -> OrderedTree:
    return OrderedTree(
        "Module",
        tuple(OrderedTree(f"Statement{i}") for i in range(node_count - 1)),
    )


def _patch_tree_distance(
    monkeypatch: pytest.MonkeyPatch,
    distance: Callable[[OrderedTree, OrderedTree], int],
) -> Callable[[], int]:
    calls = 0

    def fake_distance(left: OrderedTree, right: OrderedTree) -> int:
        nonlocal calls
        calls += 1
        return distance(left, right)

    monkeypatch.setattr(similarity, "ordered_tree_edit_distance", fake_distance)
    return lambda: calls


def _fail_similarity(left: str, right: str) -> float:
    raise AssertionError(f"unexpected Levenshtein fallback for {left!r}, {right!r}")
